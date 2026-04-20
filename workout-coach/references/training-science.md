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
| Recovery state / session timing    | §9 HRV-Guided Training |
| Cardio prescription / VO2 max      | §10 Cardio & Longevity |
| Fatigue management / periodization | §11 Deload Protocol |
| Diet, meds, demographics           | §12 User Context |
| Data gaps in the tracker           | §13 Tracker Blind Spots |
| Choosing a training split           | §14 Split Selection |
| Week-to-week progression within a block | §15 Mesocycle Structure |
| Pairing exercises / supersets      | §16 Exercise Pairing |
| Regional coverage within a muscle  | §17 Exercise Variation |
| Planning workouts / programming    | §1-§11, §14-§17 combined |

---

## §1 Volume

Dose-response is logarithmic with diminishing returns (Pelland 2024; Schoenfeld 2019). Marginal gains shrink past ~12 sets/week.

Per-session ceiling: ~6-8 hard sets per muscle with 2+ min rest (Weightology 2025). >16 sets/session may inversely affect gains (Benito 2024).

Weekly landmarks (RP Strength):
- MV (Maintenance): ~6 sets/week
- MEV (Minimum Effective): 8-12 sets/week
- MAV (Maximum Adaptive): individual, between MEV and MRV
- MRV (Maximum Recoverable): ~20-25 upper bound, varies dramatically

Muscle-specific:
- Triceps: need dedicated volume beyond pressing synergy (Baz-Valle 2022)
- Side/rear delts: poorly stimulated indirectly; need isolation
- Calves: high type-I fiber; tolerate higher volume and frequency
- Back: tolerates high volume; most lifters undertrain it
- Quads/biceps: no benefit beyond moderate (12-20) vs high (20+) weekly sets (Baz-Valle 2022)

Fractional sets: Compound = 1 set prime mover, ~0.5 synergists. Row = 1 back + 0.5 biceps. Bench = 1 chest + 0.5 triceps + 0.5 front delt.

Frequency: 2-3x/week per muscle distributes volume better. Per-session cap makes higher frequency necessary for adequate weekly totals.

## §2 Proximity to Failure

Hypertrophy improves closer to failure. Strength similar across wide RIR range (Robinson 2024, Sports Med meta-regression). 1-2 RIR = equivalent hypertrophy to failure with less fatigue (Refalo 2024).

Without RIR/RPE in tracker, stimulus quality is invisible. Flag every report.

## §3 Rest Periods

>60s rest = small hypertrophic benefit via preserved volume load. No difference between 90s and 3min+ (Singer 2024, Bayesian meta-analysis). Old NSCA 30-60s recommendation outdated.

Practical: 90s-3min compounds, 60-90s isolation. Self-selected rest likely adequate.

## §4 Rep Ranges

Moderate (6-12RM) and light (12-30RM) = similar hypertrophy close to failure (Lopez 2020, network meta-analysis). Heavy (<6RM) inferior for hypertrophy, superior for strength.

For early intermediate compound tracking: 6-12 most practical.

## §5 Lengthened Position

Training at longer muscle lengths consistently superior (Pedrosa: ~2x quad; Maeo 2024: 2x hamstring; Sato: ~3x biceps). Wolf et al. (2025): lengthened partials ≈ full ROM for upper body. "Stretch-mediated hypertrophy" is a misnomer (SBS Dec 2024).

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

Bodyweight: At 78kg pursuing hypertrophy, weight should trend upward (0.25-0.5kg/week). Flat = insufficient surplus.

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

## §10 Cardio & Longevity

VO2 max: strongest all-cause mortality predictor. Low fitness = 4-6x mortality risk (Mandsager 2018, 120K+ subjects).

Zone 2: 150 min/week minimum. NOT uniquely optimal for mitochondria (higher intensity better per unit time: Inglis 2024, Granata 2018). Advantage: lowest recovery cost.

User: 1x/week is below every recommendation. Target: 3x30-45min Zone 2 + 1x/week Zone 4-5 intervals (20 min). VO2 max 48 → target 52+ (25M).

Interference: cycling < running for interference. Separate from legs by 6-24h.

## §11 Deload

Every 4-6 weeks: reduce volume 40-50%, maintain load. Not optional. Accumulated fatigue without deload increases tendon risk (§7) and masks strength.

**Tracker convention:** the user marks deload sessions by writing `Deload Workout` in the Notes column of the first row of the session. `scripts/read_tracker.py` surfaces `deloads` (list of dates) and `weeks_since_last_deload`. Use those directly — don't infer deloads from volume patterns.

## §12 User Context

25M, 180cm, 78kg, Berlin. Early intermediate (squat/DL 60-70kg). Strict vegan 10yr. Protein 2.0-2.2g/kg (156-172g) due to low plant leucine. PrEP daily (tenofovir → BMD risk; weight-bearing compounds protective). 10g creatine/day. 900mg Ca + D3 5000IU + K2. HRV weekday 30-40ms / weekend 60-70ms. Sleep 7.5-8h, 95%+. No blood work. No deloads. No effort tracking. No bodyweight trend. No protein tracking.

## §13 Tracker Blind Spots

Flag every report:
1. No effort column (RIR/RPE) — junk volume vs effective volume indistinguishable
2. No rest period tracking — session density invisible
3. No bodyweight trend — energy balance unknown
4. No protein intake — most important nutritional variable unmeasured

## §14 Split Selection

The split must match the user's available sessions per week. The choice of split type matters less than most people think.

**Key evidence:** When weekly volume is equated, split type (full-body vs. split routine) does not significantly affect strength or hypertrophy (Ramos-Campo et al. 2024, meta-analysis). Frequency per muscle group also has negligible independent effect on hypertrophy when volume is equated (Pelland et al. 2024, 67 studies, 2058 subjects). Schoenfeld et al. (2016) found 2x/week superior to 1x/week, but no clear advantage for 3x over 2x.

The real reason to choose a split: volume distribution. The per-session ceiling of 6-8 hard sets per muscle (§1) means you can't cram a full week's volume into one session. Higher session counts let you spread volume across the week without exceeding that ceiling. The split itself is a logistics tool, not a growth driver.

Decision framework:
- **2 sessions/week:** Full body. Only option that hits each muscle 2x. Volume will be near MV for most muscles; accept this.
- **3 sessions/week:** Full body or upper/lower/full. Both work. Full body 3x distributes volume more evenly.
- **4 sessions/week:** Upper/lower 2x. Clean volume distribution. Default recommendation at this frequency.
- **5 sessions/week:** Upper/lower + rotating session, or PPL + upper/lower hybrid. Straight PPL only hits each muscle ~1.7x/week.
- **6 sessions/week:** PPL 2x. High volume capacity. Only appropriate if recovery supports it (check HRV, sleep, stress).

Because the split type itself doesn't drive hypertrophy, personal preference and logistics matter. If the user has a working split, keep it unless it creates concrete problems (e.g., sessions running over 90 minutes, muscles only hit 1x/week, unbalanced volume distribution). Switching splits disrupts exercise continuity and makes progression tracking harder.

## §15 Mesocycle Structure

Each training block runs 4-6 weeks before a deload (§11). Within that block, some form of progressive overload must occur. The exact model matters less than consistency.

**What the evidence says about progression form:** Israetel et al. (2019) proposed that weekly set volume progression is the best-supported overload form within a mesocycle. Zourdos et al. (2020) rebutted that proactive week-to-week progression may be unnecessary in trained individuals, and that performance improvement itself is sufficient evidence of overload. Chaves et al. (2024) found load progression and rep progression produce equivalent hypertrophy and strength gains in early trainees. Periodization model (linear vs. undulating) does not affect hypertrophy when volume is equated (Moesgaard et al. 2022, meta-analysis; Grgic et al. 2017, meta-analysis). Undulating may have a small strength advantage in trained individuals only (Moesgaard et al. 2022).

**Practical model for this user (early intermediate):**

For compounds, use double progression: keep the weight constant, push for more reps each session until hitting the top of the prescribed range for all sets. Then add load (per §6 benchmarks) and reset to the bottom of the range. This is simple, trackable, and evidence-equivalent to more complex models for this training stage.

For isolation exercises: same double progression principle. Add weight when hitting the top of the range for all prescribed sets across 2 consecutive sessions.

Optionally add 1 set to key exercises in weeks 3-4 of a block if recovery is good. This provides a volume ramp without aggressive week-to-week jumps, which Zourdos et al. (2020) caution against.

**For exercises with less than 3 weeks of data:** Start conservatively (leave 2-3 reps in the tank) and ramp more slowly. Don't prescribe a full block progression without a known starting point.

When planning workouts, tell the user where they are in the mesocycle and what the target for each exercise is that week. Don't give them a static plan with no week-to-week direction. If performance is improving, the current stimulus is working. If a lift stalls for 2+ sessions, that's the signal to intervene (adjust load, volume, or exercise selection).

## §16 Exercise Pairing

Straight sets (finish all sets of exercise A before starting exercise B) are the default for compounds. They allow full recovery and maximum force output.

**Key evidence:** Zhang et al. (2025, meta-analysis, 19 studies, 313 participants) found supersets produce equivalent chronic adaptations in strength, hypertrophy, and endurance compared to traditional sets, while reducing session duration significantly. However, supersets increase RPE, blood lactate, and metabolic stress acutely. Agonist-antagonist supersets maintain training volume; same-muscle supersets (compound sets) reduce volume load. Robbins et al. (2010) and Paz et al. (2017) confirmed no performance cost in the agonist exercise during antagonist-paired sets.

**When to superset:**
- Antagonist pairs: e.g., bicep curl + tricep pushdown, chest fly + rear delt fly. No performance cost to either exercise. Saves time.
- Isolation + core: pairing a low-fatigue isolation movement with a core exercise is efficient and doesn't compromise either.
- Any two exercises that don't share stabilizers or fatigue pathways.

**When not to superset:**
- Two compounds that share stabilizers (e.g., bench press + overhead press). Fatigue crossover reduces performance.
- Any exercise where form breakdown under fatigue creates injury risk (heavy squats, deadlifts, barbell rows).
- If the gym is full and supersetting requires holding two stations.
- Same-muscle supersets (e.g., two chest exercises back-to-back) reduce volume load and are not recommended for hypertrophy unless intentionally used for metabolic stress.

**RPE trade-off:** Supersets feel harder. The user should expect higher perceived effort. This doesn't reduce gains, but it affects adherence. Don't superset everything in a session.

**Practical rule:** Supersets are a time-saving tool. Use them for isolation and accessory work. Keep compounds on straight sets. If the session is already within the 70-85 minute window without supersets, don't force them.

## §17 Exercise Variation

Different exercises grow different regions of the same muscle. Running the same exercises session after session under-stimulates parts of each muscle even when weekly volume is adequate. The case for variation is mechanical, not motivational.

**Key evidence:** Burke et al. (2024), 8-week within-subject trial — leg extensions produced greater whole-muscle rectus femoris thickness than leg press (5.3mm vs 2.8mm), with the effect concentrated at the mid and distal measurement sites. Leg press, in turn, favored the vastus lateralis. Zabaleta-Korta et al. (2021) and earlier regional-hypertrophy work show the same pattern beyond the quads: pressing angle shifts pec emphasis (flat vs incline), pulldown grip and elbow path shift lat emphasis (wide vs neutral/V-bar), overhead vs flat triceps work shifts long-head vs lateral-head emphasis. Matching per-muscle volume across sessions is necessary but not sufficient — the selection determines which regions actually receive the stimulus.

**Practical model:**

- **Regional coverage within a week.** For each major muscle, the week's exercises should together cover different regions. Quads: a hip-extension compound (squat or leg press) plus a knee-extension isolation (leg extension), not two copies of either. Chest: at least one flat and one incline variant across the week. Back: vertical pull plus horizontal pull, and if volume allows, a grip-variant pair (wide plus neutral/close). Triceps: one overhead movement (long head) plus one extension/pushdown (lateral/medial).
- **Cross-block rotation.** Every mesocycle (4-6 weeks, per §11 and §15), rotate 1-2 secondary variants. Flat DB press → incline DB press. Wide-grip pulldown → V-bar pulldown. Keep rotations scoped so progression tracking on at least one anchor per muscle stays continuous.
- **Anchor compounds stay.** Preserve exercises where the user is actively progressing. The double-progression model in §15 needs a stable reference. Variation lives in the isolation and accessory slots and across blocks, not in the main lifts of an active block.
- **Don't over-rotate.** Every swapped exercise costs progression data. Keep at least one stable reference per muscle so trends remain legible. Variety that shreds progression tracking is self-defeating.

**Database hooks:** `exercises-database.md` already tags variants (`◆` lengthened-position, plus angle and grip modifiers). Use those tags when picking a second variant for a muscle. Prefer variants already in the database over inventing new ones for variety's sake.
