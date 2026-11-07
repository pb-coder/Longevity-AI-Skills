# Training Science Reference

## Quick Lookup

| When analyzing...                  | Consult |
|------------------------------------|---------|
| Weekly sets per muscle group       | §1 Volume |
| Whether sets are effective         | §2 Proximity to Failure |
| Session pacing / density           | §3 Rest Periods |
| Load appropriateness               | §4 Rep Ranges |
| Exercise quality / ROM choices     | §5 Lengthened Position |
| Weight/rep trends over time        | §6 Progressive Overload |
| Injury risk / load progression     | §7 Tendon-Muscle Mismatch |
| Push vs pull balance               | §8 Push-Pull Balance |
| Recovery state / session timing    | §9 HRV-Guided Training, §18 Recovery Signals |
| Cardio prescription / VO2 max      | §10 Cardio & Longevity |
| Fatigue management / periodization | §11 Deload Protocol |
| Diet, meds, demographics           | §12 User Context |
| Data gaps in the tracker           | §13 Tracker Blind Spots |
| Choosing a training split           | §14 Split Selection |
| Week-to-week progression within a block | §15 Mesocycle Structure |
| Set structure                      | §16 Straight Sets |
| Regional coverage within a muscle  | §17 Exercise Variation |
| Recovery score / sleep / resting HR | §18 Recovery Signals |
| Per-session HR interpretation       | §19 Per-Session HR |
| Daily activity / NEAT context       | §20 Daily Activity |
| Sleep depth and consistency         | §21 Sleep Depth & Consistency |
| Cold / ice bath timing vs strength  | §22 Cold Exposure & Hypertrophy |
| Vegan protein dose / leucine threshold | §23 Vegan Protein & Leucine |
| Core / abdominal programming        | §24 Core Training |
| Planning workouts / programming    | §1-§11, §14-§24 combined |
| Break, layoff, illness or a deliberately reduced dose | `detraining-and-minimal-dose.md` |
| No gym / bodyweight-only period, and what it cannot train | `no-equipment-training.md` |

---

## §1 Volume

Dose-response is logarithmic with diminishing returns (Pelland 2025; Schoenfeld 2019). Marginal gains shrink past ~12 sets/week.

Per-session ceiling: ~6-8 hard sets per muscle with 2+ min rest (Weightology 2025). >16 sets/session may inversely affect gains (Benito 2024).

Weekly landmarks (RP Strength):
- MV (Maintenance): ~6 sets/week
- MEV (Minimum Effective): 8-12 sets/week
- MAV (Maximum Adaptive): individual, between MEV and MRV
- MRV (Maximum Recoverable): ~20-25 upper bound, varies dramatically

**These bands are generic prose, not per-muscle targets.** The per-muscle `VOLUME_LANDMARKS`
table (`constants.py`) is the source of truth and deliberately diverges from the bands above —
of its 18 entries, only 7 have an MEV in 8-12 and only 4 have an MV ≥6 sets/week. A muscle's
landmark sitting outside this section's generic band is not, by itself, evidence that the
landmark is wrong; check `VOLUME_LANDMARKS` before flagging a mismatch.

Muscle-specific:
- Triceps: need dedicated volume beyond pressing synergy (Baz-Valle 2022)
- Side/rear delts: poorly stimulated indirectly; need isolation
- Calves: soleus is type-I dominant (~70%), gastrocnemius more mixed (~50%) — "calves" is
  not one fibre-type entity (Moderate; primary sources partly inaccessible, treat exact
  splits as approximate). Fibre type does not, on its own, justify higher volume or
  frequency: no meta-analysis stratifies the volume-hypertrophy dose-response by fibre
  type, fatigue-resistance is not the same as a higher hypertrophic dose requirement, and
  Pelland 2025 found frequency has negligible independent effect on hypertrophy once volume
  is equated — the opposite of what a "type I needs more frequency" claim predicts (Thin as
  an inference). Program calves like any other muscle; don't elevate volume/frequency
  targets on fibre-type grounds alone.
- Back: tolerates high volume; most lifters undertrain it
- Quads/biceps: no benefit beyond moderate (12-20) vs high (20+) weekly sets (Baz-Valle 2022)

Fractional sets: Compound = 1 set prime mover, ~0.5 synergists. Row = 1 back + 0.5 biceps. Bench = 1 chest + 0.5 triceps + 0.5 front delt.

Frequency: 2-3x/week per muscle distributes volume better. Per-session cap makes higher frequency necessary for adequate weekly totals.

## §2 Proximity to Failure

Hypertrophy improves closer to failure. Strength similar across wide RIR range (Robinson 2024, Sports Med meta-regression). 1-2 RIR = equivalent hypertrophy to failure with less fatigue (Refalo 2024).

Without RIR/RPE in tracker, stimulus quality is invisible. When using stall or reactive-deload language, state that the signal is inferred from load/reps and not confirmed by effort-in-reserve data.

## §3 Rest Periods

>60s rest = small hypertrophic benefit via preserved volume load. No difference between 90s and 3min+ (Singer 2024, Bayesian meta-analysis). Old NSCA 30-60s recommendation outdated.

Practical: 90s-3min compounds, 60-90s isolation. Self-selected rest likely adequate.

## §4 Rep Ranges

Moderate (6-12RM) and light (12-30RM) = similar hypertrophy close to failure (Lopez 2020, network meta-analysis). Heavy (<6RM) inferior for hypertrophy, superior for strength.

For early intermediate compound tracking: 6-12 most practical.

## §5 Lengthened Position

Training at longer muscle lengths is directionally superior, but reported effect sizes vary in strength and generality — treat the headline multipliers below as illustrative, not as uniform whole-muscle effects (Pedrosa: ~2x quad growth, but from n=45 untrained women with the effect concentrated in ~70% of femur length — region-specific, not uniform; Maeo 2021: ~2x hamstring; Sato: greater distal-region hypertrophy from initial-ROM training, not a whole-muscle ~3x effect as sometimes cited, and contested by later work). Wolf et al. (2025): lengthened partials ≈ full ROM for upper body. "Stretch-mediated hypertrophy" is a misnomer (SBS Dec 2024).

Prioritize: Deep squats, RDLs, overhead triceps extensions, incline curls, DB flyes, dips.
Deprioritize: Spider curls, hip thrusts, floor presses, cable crossovers at end range.

Exercises marked ◆ in the database emphasize the lengthened position.

## §6 Progressive Overload

Primary hypertrophy driver. Forms: load, rep, volume, density.

Rate benchmarks (early intermediate, squat 60-70kg):
- Lower body compounds: ~2.5kg/week for 6-12 months
- Upper body compounds: ~1-1.5kg/week
- Isolation: ~1kg/2-4 weeks or rep progression

Flat weights and reps across weeks = single biggest red flag.

Bodyweight: during a hypertrophy-focused surplus, weight should trend
upward at roughly 0.25-0.5 kg/week. Flat = insufficient surplus.

## §7 Tendon-Muscle Mismatch

Muscle adapts faster than tendon (Lambrianides 2024). Strength increases before tendon stiffness catches up → increased strain and injury risk during rapid progression.

- Injury probability rises with rapid load increases (Gabbett 2016)
- Tendon needs high-intensity contractions (≥85% MVC), ~3s duration, repeated weeks (Kjaer 2009; Arampatzis 2007)
- Plyometric loading is weak tendon stimulus vs heavy isometric/slow eccentric

Cap progression rate. Implement deloads. Don't stack volume + intensity + novelty. Body feels stronger before it is structurally stronger.

## §8 Push-Pull Balance

Strength ratio: ~1:1 target (Baker & Newton 2004: 97.7% trained). Recreational lifters typically push-dominant (1.57:1, Negrete 2013).

Volume ratio: ≥1:1, ideally 1:1.5-1:2 favoring pulls. Emphasize horizontal pulling alongside vertical.

## §9 HRV-Guided Training

RMSSD 7-day rolling average. Morning, supine, before coffee.

User: weekday 30-40ms, weekend 60-70ms = systematic stress depression.
- Shift highest volume/intensity to weekends
- Or use HRV as go/no-go signal
- HRV-guided trends toward better outcomes (Flatt 2021: SMD 0.50)

Overreaching: RMSSD below baseline >1 SD for >3 days → reduce volume. Trends not single days.

**Source note.** Health Export Kit carries no HRV (`capabilities.hrv` is False), so this lever is unavailable to the coach. The recovery score runs without it.

## §10 Cardio & Longevity

VO2 max: strongest all-cause mortality predictor. Low fitness = 4-6x mortality risk (Mandsager 2018, 120K+ subjects).

Zone 2: 150 min/week minimum. NOT uniquely optimal for mitochondria (higher intensity better per unit time: Inglis 2024, Granata 2018). Advantage: lowest recovery cost.

For low cardio frequency, a default target is 3x30-45 min Zone 2 plus
1x/week Zone 4-5 intervals (about 20 min). Apply VO2max targets from
the person's private age/sex profile rather than hardcoding a number.

Interference: same-session cardio + strength produces the worst lower-body hypertrophy outcome (Schumann 2022 meta-analysis, Sports Medicine). Temporal separation of 3-6 hours largely neutralizes the effect; longer is fine but not required. Modality matters more than intensity: impact-eccentric cardio (running) compounds with strength-induced damage, low-impact concentric modalities (cycling, swimming, rowing) don't (Casuso N=18 inflammation comparison). Total cardio duration is the dominant variable, not bioenergetic zone. For early intermediate trainees, interference is a minor practical concern; specialization-driven divergence emerges near genetic ceiling.

### §10.1 VO2max interpretation

The Apple Watch VO2max estimate (`vo2max_latest` in `read_tracker.py`) is a regression model fit on outdoor walking/running with HR. It tracks real changes well; absolute calibration is approximate. Use trend more than the single number.

Targets are age- and sex-dependent. Use `vo2_percentile` /
`vo2_percentile_age_sex` from `health_longevity.py` when framing the
current value; do not hardcode one M30s table for every person. Coach copy
should say the percentile band and then lean on the 4-week trend for action.

Expected response to consistent Zone 2 + intervals: 1-3 ml/kg/min over 6-12 weeks for an early-intermediate trainee. Faster gains usually mean the baseline measurement was low, not that the user is responding extraordinarily.

Interpretation rules:
- VO2max flat (slope per 4w near 0) AND `cardio_last_28d` shows targets met → cardio is maintaining, not progressing. Suggest adding intensity (more intervals, faster Zone 2 splits) before adding volume.
- VO2max declining AND cardio targets met → check sleep and resting HR first; chronic under-recovery suppresses VO2max.
- VO2max declining AND cardio targets missed → it's a dose problem. Don't over-interpret. Restore the prescribed cardio.
- VO2max climbing → keep doing what's working. Don't change the program for "variety."

Single-reading caveat: Apple emits VO2max episodically (post-walk, post-run). One number after a hot or under-slept day can swing ±2 ml/kg/min. The 4-week slope is the signal.

## §11 Deload

Default cadence: every 4-6 weeks, reduce volume 40-50%, maintain load. Accumulated fatigue without deload increases tendon risk (§7) and masks strength.

Primary evidence for the scheduled-vs-reactive question (Established for hypertrophy equivalence; Moderate for the strength nuance):
- Pancar et al. 2026 (Sci Rep, N=19, 8 weeks, within-subject): scheduled volume-reduction deloads at weeks 4 and 8 produced equivalent quadriceps hypertrophy to continuous training. Between-condition difference in lateral quad thickness was -0.76 mm (95% CI -2.20 to 0.68, p=0.282).
- Coleman et al. 2024 (PeerJ, N=39, 9 weeks): a single mid-block total-cessation week produced equivalent hypertrophy but inferior 1RM gains vs continuous training. Hypertrophy is forgiving of brief interruption; max strength gain is not.
- Lambrianides et al. 2024 (Scand J Med Sci Sports, 12 weeks): muscle force capacity rose ~6% by week 2; Achilles tendon stiffness, modulus, and CSA showed no change at week 8 and only emerged at week 12 (stiffness +13%, modulus +7%, CSA +6%). This is the biological anchor for keeping a calendar ceiling on training-block length independent of performance autoregulation.

Autoregulation alternative (Helms 2023-25, practitioner consensus; Promising): for advanced lifters near MRV with reliable RIR / RPE tracking, reactive deloads triggered by performance decay can replace the calendar cadence. Trigger: failure to hit prescribed loads at the prescribed RIR across 2-3 sessions. Without RIR (§13) or load-velocity profiling, reactive can't be applied honestly; subjective psychological fatigue contaminates the signal. The tracker's `auto_deload_candidates` detector approximates the reactive trigger from volume and bar-speed proxies; it's a hint, not a substitute for RIR.

**Tracker convention:** the user marks deload sessions by writing `Deload Workout` in the Notes column of any row of the session; the styler hoists the marker to the session's TOTAL row Notes. `scripts/read_tracker.py` surfaces `deloads` (list of dates) and `auto_deload_candidates` (Python-detected, unmarked candidates the user might have forgotten to flag). Compute weeks-since-last-deload from `deloads[-1]` and `today`; don't infer deloads from volume patterns directly — the auto-detector already does that conservatively.

## §12 User Context

Do not store private person profiles in committed reference docs. Load
person-specific context from `<Person>/data/profile.csv`,
`<Person>/data/longevity/*.md`, and the tracker JSON emitted by
`scripts/read_tracker.py`.

Committed training-science references should stay generic: use the
rules, thresholds, and citations in this file, then apply them to the
private tracker data at runtime.

## §13 Tracker Blind Spots

Flag every report:
1. No effort column (RIR/RPE) — junk volume vs effective volume indistinguishable
2. No rest period tracking — session density invisible
3. No bodyweight trend — energy balance unknown
4. No protein intake — most important nutritional variable unmeasured

## §14 Split Selection

The split must match the user's available sessions per week. The choice of split type matters less than most people think.

**Key evidence:** When weekly volume is equated, split type (full-body vs. split routine) does not significantly affect strength or hypertrophy (Ramos-Campo et al. 2024, meta-analysis). Frequency per muscle group also has negligible independent effect on hypertrophy when volume is equated (Pelland et al. 2025, 67 studies, 2058 subjects). Schoenfeld et al. (2016) found 2x/week superior to 1x/week, but no clear advantage for 3x over 2x.

The real reason to choose a split: volume distribution. The per-session ceiling of 6-8 hard sets per muscle (§1) means you can't cram a full week's volume into one session. Higher session counts let you spread volume across the week without exceeding that ceiling. The split itself is a logistics tool, not a growth driver.

Decision framework:
- **2 sessions/week:** Full body. Only option that hits each muscle 2x. Volume will be near MV for most muscles; accept this.
- **3 sessions/week:** Full body or upper/lower/full. Both work. Full body 3x distributes volume more evenly.
- **4 sessions/week:** Upper/lower 2x. Clean volume distribution. Default recommendation at this frequency.
- **5 sessions/week:** Upper/lower + rotating session, or PPL + upper/lower hybrid. Straight PPL only hits each muscle ~1.7x/week.
- **6 sessions/week:** PPL 2x. High volume capacity. Only appropriate if recovery supports it (check sleep, resting HR, stress).

Because the split type itself doesn't drive hypertrophy, personal preference and logistics matter. If the user has a working split, keep it unless it creates concrete problems (e.g., sessions running over 90 minutes, muscles only hit 1x/week, unbalanced volume distribution). Switching splits disrupts exercise continuity and makes progression tracking harder.

## §15 Mesocycle Structure

Each training block runs 4-6 weeks before a deload (§11). Within that block, some form of progressive overload must occur. The exact model matters less than consistency.

**What the evidence says about progression form:** Israetel et al. (2019) proposed that weekly set volume progression is the best-supported overload form within a mesocycle. Zourdos et al. (2020) rebutted that proactive week-to-week progression may be unnecessary in trained individuals, and that performance improvement itself is sufficient evidence of overload. Chaves et al. (2024) found load progression and rep progression produce equivalent hypertrophy and strength gains in early trainees. Periodization model (linear vs. undulating) does not affect hypertrophy when volume is equated (Moesgaard et al. 2022, meta-analysis; Grgic et al. 2017, meta-analysis). Undulating may have a small strength advantage in trained individuals only (Moesgaard et al. 2022).

**Practical model for an early intermediate trainee:**

For compounds, use double progression: keep the weight constant, push for more reps each session until hitting the top of the prescribed range for all sets. Then add load (per §6 benchmarks) and reset to the bottom of the range. This is simple, trackable, and evidence-equivalent to more complex models for this training stage. The range tops out at 12 reps for compounds and 20 for isolation: past that, more reps are more endurance, and the lift is owed weight. `next_dose` applies this rule from the log and the coach copies it.

For isolation exercises: same double progression principle, with the range topping out at 20 reps. Add weight when every working set reaches the top of the range.

Optionally add 1 set to key exercises in weeks 3-4 of a block if recovery is good. This provides a volume ramp without aggressive week-to-week jumps, which Zourdos et al. (2020) caution against.

**For exercises with less than 3 weeks of data:** Start conservatively (leave 2-3 reps in the tank) and ramp more slowly. Don't prescribe a full block progression without a known starting point.

When planning workouts, tell the user where they are in the mesocycle and what the target for each exercise is that week. Don't give them a static plan with no week-to-week direction. If performance is improving, the current stimulus is working. If a lift stalls for 2+ sessions, that's the signal to intervene (adjust load, volume, or exercise selection).

## §16 Straight Sets

Every exercise is trained as straight sets: finish all sets of exercise A, with its full rest, before starting exercise B. No pairing, alternating or circuits, for compounds and isolation alike. This is a standing user preference, not an evidence call.

Straight sets allow full recovery between sets and maximum force output on each one. When a session runs long, cut a set or an exercise; do not compress rest by pairing movements.

## §17 Exercise Variation

Different exercises grow different regions of the same muscle. Running the same exercises session after session under-stimulates parts of each muscle even when weekly volume is adequate. The case for variation is mechanical, not motivational.

**Key evidence:** Burke et al. (2024), 8-week within-subject trial — leg extensions produced greater whole-muscle rectus femoris thickness than leg press (5.3mm vs 2.8mm), with the effect concentrated at the mid and distal measurement sites. Leg press, in turn, favored the vastus lateralis. Zabaleta-Korta et al. (2021) and earlier regional-hypertrophy work show the same pattern beyond the quads: pressing angle shifts pec emphasis (flat vs incline), pulldown grip and elbow path shift lat emphasis (wide vs neutral/V-bar), overhead vs flat triceps work shifts long-head vs lateral-head emphasis. Matching per-muscle volume across sessions is necessary but not sufficient — the selection determines which regions actually receive the stimulus.

**Practical model:**

- **Regional coverage within a week.** For each major muscle, the week's exercises should together cover different regions. Quads: a hip-extension compound (squat or leg press) plus a knee-extension isolation (leg extension), not two copies of either. Chest: at least one flat and one incline variant across the week. Back: vertical pull plus horizontal pull, and if volume allows, a grip-variant pair (wide plus neutral/close). Triceps: one overhead movement (long head) plus one extension/pushdown (lateral/medial). Shoulders: one vertical (overhead) press plus lateral-delt isolation, with rear-delt work as available; a split change must not drop the press.
- **Same split, second exposure.** In a 4-session week where Push/Pull/Legs repeats one day, vary the repeated day inside the week. Keep one anchor stable for progression, but change the lead angle/pattern or the isolation slot so the repeat covers a different region instead of duplicating session one.
- **Cross-block rotation.** Every mesocycle (4-6 weeks, per §11 and §15), rotate 1-2 secondary variants. Flat DB press → incline DB press. Wide-grip pulldown → V-bar pulldown. Keep rotations scoped so progression tracking on at least one anchor per muscle stays continuous.
- **Anchor compounds stay.** Preserve exercises where the user is actively progressing. The double-progression model in §15 needs a stable reference. Variation lives in the isolation and accessory slots and across blocks, not in the main lifts of an active block.
- **Stale reintroductions start conservatively.** If a movement has been absent for 8+ weeks, has only one logged session, or carries context-change notes, do not infer its restart load from e1RM. Use the last reliable working load only with multi-session history; otherwise prescribe a submaximal load and 2-3 reps in reserve for the first exposure.
- **Don't over-rotate.** Every swapped exercise costs progression data. Keep at least one stable reference per muscle so trends remain legible. Variety that shreds progression tracking is self-defeating.

**Database hooks:** `exercises-database.md` already tags variants (`◆` lengthened-position, plus angle and grip modifiers). Use those tags when picking a second variant for a muscle. Prefer variants already in the database over inventing new ones for variety's sake.

## §18 Recovery Signals

**Source dependency.** Health Export Kit carries no all-day HRV and no wrist temperature (`capabilities.hrv` and `capabilities.wrist_temp` are False), so the recovery score runs without them. The score's `confidence` field surfaces missing or sparse signals. Standard re-entry / deload heuristics still apply on any source.

The signals that move the recovery picture here: resting HR, total sleep, deep and REM sleep, HR Recovery 1-min, and sleep consistency. VO2max trend is a chronic-fitness signal and stays out of the score. Single-day values are noisy; the score uses 7-day means (5-day for HR Recovery) against 28-day personal baselines.

**`recovery` is the primary read.** `scripts/read_tracker.py` returns:

```
recovery: {score: 0-10 | null, confidence: low|medium|high, drivers: [...]}
```

Each signal is a z-score against the person's own baseline, mapped to a 0-10 component (5 = their average), and the score is the weighted average over the signals that have enough sample. Missing signals leave the rest to vote; they do not pull the score down. `score` is null when no signal had sample, typically when there is no recent health import. `confidence`: high (4 or more contributing signals), medium (2-3), low (fewer).

| Signal | Raw weight | Reading |
|---|---|---|
| Sleep total | 0.20 | Recent 7d vs 28d baseline. |
| Resting HR | 0.15 | Lower is better (inverted). |
| HR Recovery 1-min | 0.10 | Recent 5d vs 28d. Higher = recovered. |
| Sleep deep / REM | 0.05 each | Needs `sleep_stages`. |
| Sleep consistency | 0.05 | Penalty-only. |

(HRV at 0.30 and wrist temperature at 0.10 are capability-gated and absent for this source.)

**Programming consequences.** The score reaches the plan through the session gate (`session_recommendation`), whose tier and `load_policy` decide whether the day is normal, scaled or a deload, and through `next_dose`, which decides loads. The score is not a second load rule:
- A low score is Tier C or worse in the gate; lead with the dominant negative driver on the recovery-drivers card.
- A negative driver persisting across several `health_metrics_weekly` entries is a reason to look harder at a deload; the gate and the deload clock (`block.deload_cadence_due`) make the call.
- Always surface the reason on the card: the user should know why the day is conservative.

**What NOT to do:** infer overreaching from one bad night (the score already smooths over 7 days), or recommend the user "track HRV better" or "track wrist temperature" (`capabilities.hrv` and `capabilities.wrist_temp` are False: a source limitation, not a tracking gap).

## §19 Per-Session HR

**Source dependency.** This section needs per-workout HR on strength rows, which Health Export Kit provides. The capability gate in `read_tracker.py` (`capabilities.per_workout_hr_strength`) short-circuits the cross-check on partial trackers; the standard load-progression rule (`next_dose`) still drives their plans.

Apple emits per-workout HR statistics (avg / max / min) on every `Workout` record. The importer matches these to logged training by date. `read_tracker.py` folds avg_hr + max_hr onto each `monthly_sessions[*]` entry and exposes per-muscle HR-creep flags via `hr_at_volume_divergence`.

**Strength sessions, avg HR bands:**
- 130-150 bpm avg = normal hypertrophy stimulus. Don't comment.
- 150-160 bpm avg = running hot. Either rest periods are too short, accessory volume is too high, or the user is under-recovered. Tighten rest periods or trim accessory sets; add no sets this block.
- >160 bpm sustained = under-recovered or excessive density. Investigate before progressing anything.
- <110 bpm avg = effort too light. The user is leaving stimulus on the table — push reps before adding load.

**Trend matters more than absolute.** A user with a low resting HR and good cardiac fitness can run a session at 125-135 bpm and hit failure on every set; another can sit at 145 bpm with the same effort. The cleanest fatigue signal is **per-muscle HR creep at constant volume** — `hr_at_volume_divergence[muscle].slope_bpm_per_4w` controls for volume changes that would otherwise confound the read. `hint == "rising HR at constant volume"` (slope ≥ +5 bpm/4w with ≥6 sessions) means the body is working harder for the same output. Add no sets to that muscle group, finish the block, then deload; loads still follow `next_dose`.

**Cardio sessions, avg HR bands** (for Apple workouts of type Running / Cycling / Walking / Outdoor* / Indoor*):
- Zone 2: 65-75% of max HR. Compute the actual range from the person's estimated max HR; if the average drifts above the upper band, the session was tempo, not Zone 2.
- Intervals: avg HR is meaningless for intervals — read max HR (should hit 165+ during work blocks).

**What NOT to do:** match a stretching session's low HR to "low effort" (different stimulus type), compare across activity types, or react to a single high-HR session without a 4-session window. Sleep/caffeine/heat affect HR substantially day-to-day.

## §20 Daily Activity (NEAT)

NEAT — non-exercise activity thermogenesis — captures everything that isn't a logged workout: walking, errands, climbing stairs, fidgeting, standing desk work. For someone training 4x/week, NEAT is often the larger contributor to daily energy expenditure and the larger contributor to baseline aerobic conditioning.

**Why it matters for the coach.** Two users with identical workout volume can have very different aerobic-load pictures. A user who walks 90 min/day to and from the gym is already getting Zone-1-to-2 stimulus from those walks; prescribing 3x weekly Zone 2 sessions on top doubles down on what they have. A user who drives to the gym and works at a desk gets zero passive aerobic load — for them, the §10 cardio targets are the floor, not the ceiling.

**Apple's `exercise_min` is the canonical NEAT signal** when available. It counts minutes of brisk movement (heart rate elevated above resting), which is roughly the same threshold as Apple's Exercise Ring. Apple's recommended baseline is 30 min/day; 45+ min/day is "active". When `exercise_min` is unavailable, `walking_minutes_28d / 28` is a reasonable NEAT proxy — daily walking is the dominant non-exercise movement signal.

**Assessment thresholds** (from `daily_activity_28d.assessment`):
- `low` (<15 min/day) — sedentary baseline. Cardio prescription becomes more important, not less. Add at least one Zone 2 session even if 28d cardio targets are nominally met.
- `moderate` (15-45 min/day) — typical desk worker who walks. Standard §10 rules apply.
- `high` (≥45 min/day) — active baseline. If VO2max is also trending up, the user is already getting aerobic load passively; cardio prescription can be light. Prefer one interval session for the VO2max stimulus over multiple Z2 sessions.

**Programming consequences:**
- A `low` assessment with VO2max trending down is a stronger deload-flag signal than the same VO2max trend at `high` baseline activity. The high-baseline user can absorb more session load without their aerobic ceiling drifting.
- A `high` assessment combined with under-MAV strength volume often points to the user being chronically under-fed (body composition drifting because energy out > energy in). Bodyweight trend is the cross-check.

**What NOT to do:** treat one high-NEAT week as durable — the assessment is a 28-day rollup so day-to-day fluctuation is already smoothed; reduce strength volume because passive activity is high (passive activity doesn't substitute for resistance stimulus, only for aerobic conditioning); recommend "walk more" without a number — cite the band and the threshold.

## §21 Sleep Depth & Consistency

Total sleep hours is the headline metric, but two users sleeping 7h/night can have very different recovery quality if one of them gets 18% deep sleep and the other gets 8%. Sleep depth is where physical recovery happens — growth hormone secretion, glymphatic clearance, glycogen restocking. REM sleep is where neuromotor consolidation happens — skill retention, technique cementation.

**Healthy ranges** (Walker 2017, AASM consensus):
- Deep sleep: 13-23% of total. <13% sustained across 5+ nights is a recovery deficit even at adequate total hours. >23% is rare and usually signals deep-recovery rebound after an under-slept stretch.
- REM sleep: 20-25% of total. <20% sustained signals neuromotor recovery is short. Alcohol, late caffeine, late carbs all suppress REM disproportionately.

**Sleep consistency** is its own signal. Stdev of nightly totals over a 7-night window: <1.0h is regular, 1.0-1.5h is acceptable, >1.5h is irregular and stressful regardless of average. The body adapts to consistent timing — a 6h/6h/6h/6h/6h/9h/9h week is worse than 6.5h/6.5h/6.5h/6.5h/6.5h/6.5h/6.5h despite the same total.

**Source dependency.** Health Export Kit carries deep / REM / core / awake breakdowns from watch-side sleep staging (calibrated against PSG). The capability gate `sleep_stages` in `read_tracker.py` short-circuits the deep/REM drivers on legacy or partial trackers; sleep_total_h and sleep consistency still apply whenever present.

**Programming consequences** (applied by `recovery_score`):
- `sleep_deep_pct < 13%` and persisting → -0.4 contribution to recovery score. Combined with low total hours, prefer a deload window.
- `sleep_rem_pct < 20%` and persisting → -0.4 contribution. Less impact on strength sessions; bigger impact on technical-skill work and complex compounds.
- `sleep_consistency_7d_stdev_h > 1.5h` → -0.4 contribution. The fix is bedtime regularity, not more total hours.

**What NOT to do:** weight a single night's poor depth heavily (1-2 bad nights are normal); recommend "sleep more" when consistency is the actual issue; ask users to "track sleep stages better" when `capabilities.sleep_stages` is False — that's a source limitation, not a tracking gap.

## §22 Cold Exposure & Hypertrophy

Cold water immersion (CWI) within ~4-6 hours of a resistance session blunts mTOR signaling and satellite cell activation, reducing long-term muscle growth. Roberts et al. (2015) showed an attenuated hypertrophy response across a 12-week trial; subsequent meta-analyses through 2024 (e.g., Piñero et al. 2024, Wang et al. 2024) confirm the effect across cold modalities and body regions. Evidence tier: Established for the acute anabolic blunting; Promising for the magnitude of long-term loss in trained populations.

Practical rules:
- Ice baths and cold plunges belong on rest days, or separated from strength work by 4-6+ hours.
- Sauna post-workout does not blunt hypertrophy and may mildly support recovery via heat shock protein induction (see longevity-optimizer `response-triggers.md`, Thermal Stress). Heat can immediately follow lifting; cold cannot.
- For pure endurance sessions where same-day soreness reduction matters and hypertrophy isn't a goal, the rule inverts.

When the user asks about post-workout recovery and mentions cold, name the trade-off explicitly: less soreness now, less muscle later. Don't bury it.

## §23 Vegan Protein & Leucine

Total daily protein 2.0-2.2 g/kg from varied plant sources matches omnivorous diets for longitudinal hypertrophy when total intake is equated. Evidence tier: Established.

Primary evidence:
- Hevia-Larraín et al. 2021 (Sports Med, N=38 trained males, 12 weeks, 1.6 g/kg matched): leg lean mass gain vegan +1.2 ± 1.0 kg vs omnivore +1.2 ± 0.8 kg; vastus lateralis CSA +2.2 ± 1.1 cm² vs +2.8 ± 1.0 cm², p > 0.05 across all between-group comparisons.
- Monteyne et al. 2023 (J Nutr): equivalent daily myofibrillar protein synthesis and leg lean mass in vegans vs omnivores at high protein intake.
- Pinckaers et al. 2021 (Br J Nutr): wheat protein, milk protein, and wheat-milk blend produce equivalent acute MPS in healthy young males. Casein-style "slow protein" advantage disappears when leucine threshold is met.

Per-meal leucine threshold: ~2.5-3.0 g of leucine to saturate mTORC1. Plant proteins are lower in leucine by mass (wheat ~7%, soy ~8%, whey ~11%), so vegans need a larger absolute protein dose per meal to clear the threshold. Practical rule: 30-40 g plant protein per meal, distributed across 3-5 meals to repeatedly trigger MPS.

Pre-sleep protein: there is no casein analogue in plants, but a pea + wheat blend (or a vital wheat gluten + pea protein shake) approximates slow release and balances limiting amino acids (wheat is low in lysine; pea is low in methionine). Acute MPS rates are equivalent (Pinckaers 2021).

Supplemental free leucine, BCAAs, EAAs, and HMB add no measurable hypertrophy benefit above a well-distributed 2.0-2.2 g/kg vegan diet. Don't recommend them for hypertrophy. (The "acute MPS amplitude" advantage shown in 3-hour isotope-tracer studies normalizes over 24-hour integration when total daily protein exceeds 1.6 g/kg.)

Creatine and vegans: 5 g/day monohydrate amplifies strength and lean-mass gains slightly more in vegans than omnivores due to lower baseline intramuscular phosphocreatine (Solis 2020, Burke 2003). Once intramuscular saturation is reached, the relevant marker is maintenance, not further dose escalation. The high creatinine artifact on standard eGFR is real and is addressed in `longevity-optimizer/references/biomarkers.md` Interpretation Notes.

## §24 Core Training

Core means rectus abdominis and obliques; erectors are a separate landmark. Treat it as a hypertrophy target. Read [core-evidence.md](core-evidence.md) when changing core selection, responding to poor core adherence, or explaining/challenging the evidence. The detailed selection ladders and citations live there.

- Take dose, diversity, category and repetition limits from `core_week_spec` and `muscle_volume_targets["core"]`, not hardcoded prose. These are blocking plan checks. The abdominal dose landmarks are practitioner heuristics extrapolated from limb data; no trial establishes an abdominal set-volume dose-response.
- Slot A: at least one externally loaded flexion movement weekly. Slot B: rotate non-flexion categories by block (anti-extension, anti-rotation, anti-lateral-flexion, rotation). Prefer loadable movements within each slot; do not let loadability collapse the whole plan into flexion. Read the detailed ladders before changing the block's selection.
- Place core inside the isolation block as straight sets, after compounds. Neither core nor direct arms may be the last exercise. Introduce unfamiliar movements early enough to be performed. Completion history outranks theoretical selection quality; change repeatedly skipped movements or their placement.
- Progress loaded core through the same double progression as other isolation work. Unloaded holds progress through time, leverage or range; the current progression analytics cannot represent those changes. Prefer movements that can accept load; do not change the CSV schema to manufacture a progression series. Never mark prescribed core optional.
- Compounds feed erector volume, not direct abdominal volume. Two-handed farmer walks earn no ab credit and are finishers outside the core budget. Suitcase carries count toward core; prescribe both sides. Plate Around the World is a mechanistic anti-rotation analogy with no direct study support and cannot satisfy loaded flexion.
- Healthy trainees need not avoid spinal flexion; adapt to symptoms and individual constraints. Do not invent separate upper/lower-ab muscles or track a core-stability metric. Detailed evidence and safety limitations are in the companion reference.
- Justify core for abdominal hypertrophy, not proven transfer to squat/deadlift strength. Direct abdominal training has supportive intervention evidence, but studied populations and dose limit generalization. Compound-only maintenance is conditional, not proof direct work never matters.
- Body fat dominates abdominal visibility; spot reduction is unsupported. Do not promise a visible-abs body-fat percentage or equate more ab sets with fat loss. Whether hypertrophy changes visibility at matched body fat remains untested.
