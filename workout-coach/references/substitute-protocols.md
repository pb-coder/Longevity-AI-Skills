# Substitute protocols — what to write when the gate restricts strength

When `session_recommendation.tier` is **A**, **B**, or **C**, the coach does NOT write the planned strength session as-is.

- **Tier C** is automatic: fill the markdown from the Tier C template below.
- **Tier A and B are never decided alone.** Stop after `read_tracker`, before writing `coach_reads.json` or the plan, and ask the user in chat (protocol below). Fill the markdown from the template for the option they choose.

Reasoning behind the gate is in the Phase 2 preamble of `SKILL.md`. The thresholds and per-tier triggers are in `lib/constants.py:SESSION_GATE_THRESHOLDS`. The decision lives in `lib/health_session_rec.py:compute_session_recommendation`, which also attaches the `load_policy` (`progress` or `reduce`) that `next_dose` applies.

**No template contains cardio, and no plan does.** Cardio data feeds the gate and the assessment; it is never prescribed. The gate's `substitute.kind` can still read `zone_2`: that names the gate's own read of the signals, and it is one of the reasons you show the user when you ask, not a section to write.

**The templates below are copy-me markdown and `validate_workout_md` runs over the result.** Its em-dash rule allows one only on the `# Workout plan — <date>` title line and on an indented `  — cue` sub-bullet. A `> Today's call:` or `> Why:` line is neither, so an em-dash there is a blocking error and `check_plan.py` exits 2. Use a period, comma, semicolon or colon when you fill these in.

**The `Assessment: ./<date>-assessment.html` line** appears in every template below. Write it only on a run that renders the report; leave it out otherwise.

---

## Tier A (`rest`) and Tier B (`reactive_deload`): ask first

Tell the user, in one short message (or a structured question when the client offers one):

- the tier and its `label`, plus `substitute.kind`;
- the gate's `headline`;
- the `rationale` notes that fired it.

Then offer three options and wait for the answer:

1. **Rest day.** Use the rest-day template below.
2. **Lighter strength**: fewer sets, held weights. Use the lighter-strength template below, against the tracker JSON as it is. On Tier A and on `reactive_deload` the set budget is half the base, and `check_plan.py` judges each session against it (advisory, like every budget finding). On Tier A and on `reactive_deload` the core volume findings and the per-muscle weekly floors drop to warnings (it is a declared deload), while diversity and placement stay blocking. `load_policy` is `reduce`: loads are held and sets are cut.
3. **Normal strength anyway**, for example planned for the following week. Regenerate the tracker JSON with `read_tracker.py --override-gate`, then follow "Override behavior" at the end of this file.

Do not suggest a default beyond the gate's own call, and do not write any file until the user has answered.

---

## Option 1 — Rest day

```markdown
# Workout plan — <date>
> Today's call: <session_recommendation.headline>
> Why: <rationale[0].note>
>      <rationale[1].note>
>      <rationale[2].note>

Assessment: ./<date>-assessment.html

## Rest day
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- Hydration: front-load fluids today
- Sleep priority: 8h target tonight, no caffeine after noon

## Re-evaluate tomorrow
Date: ___

- Check resting HR and last night's sleep in the morning before deciding the next session
- If resting HR is back at baseline and the next `/coach` run reads Tier C or better, the next planned session is back on
```

**Do not** add strength alternatives or any cardio. **Do not** offer "if you feel better, do X". The user already chose rest.

---

## Option 2 — Lighter strength (full-block deload week)

Fewer sets, held weights. The markdown lists the lighter workouts for the whole week, in the normal workout format: `## Workout N: <TYPE>` headings (not "Deload Session"), every set its own `///` entry, sub-bullets only for a real cue.

```markdown
# Workout plan — <date>
> Today's call: <session_recommendation.headline>
> Why: <rationale[0].note>
>      <rationale[1].note>

Assessment: ./<date>-assessment.html

Lighter strength this week: half the sets, weights held. No finisher.

## Workout 1: UPPER A + CORE
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- Jumping Jacks: 50
- Arm Circles: 20
- Dumbbell Flat Bench Press: 50kgx8-10 /// 50kgx8-10
- Cable Lat Pulldown: 60kgx8-10 /// 60kgx8-10
- Cable Lateral Raise: 10kgx12-15 /// 10kgx12-15
- Kneeling Cable Crunch: 20kgx12-15 /// 20kgx12-15
- Cable Face Pull: 20kgx12-15 /// 20kgx12-15

## Workout 2: LOWER A + CORE
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- <…>
```

How to fill it:

- One `## Workout N: <TYPE>` block per session; the user's session count (the `/coach plan N sessions` arg) sets N. Keep the week's normal selection and split.
- Every load is `next_dose.exercises[].load_kg` and every range its `rep_range`. Under `reduce`, `next_dose` already holds each load; a `hold` entry is treated the same way (keep its load, halve its sets).
- Halve each exercise's working sets (4 becomes 2, 3 becomes 2, 2 stays 2), one `///` entry per set kept. Core keeps its per-session dose (4 sets lower, 2 upper). The normal placement rules still apply: core and arms inside the isolation block, something that is neither last.
- Do not write "hold load" or "halve sets" in a sub-bullet: the validator warns on that phrasing, and the opener already says it.
- If an over-MRV muscle drove the gate, rotate its exercise to a different movement pattern (e.g. flat bench to incline DB).
- Return to normal volume next week if the next `/coach` run reads Tier C or better.

---

## Tier C — `modified_strength` (downgrade)

Same session pattern as the planned workout, with the budget cut and nothing else held back:

- **Volume**: the working-set budget is scaled x0.6 for workouts `1..expected_rebound_by_session` (inclusive); later workouts keep the full budget. `target_working_sets` is unscaled in the payload, so multiply it yourself. The `hold_load` variant of Tier C keeps the full budget.
- **Loads**: NOT held. Every load and rep range is copied from `next_dose`: a lift that earned weight gets it. Only `load_policy` `reduce` (Tier A / B, or strength TSB of -15 or lower) holds loads.
- **Finisher**: drop any finisher.
- **Warm-up**: unchanged. Keep the two prep movements and the ramp sets into the first heavy compound. A recovery downgrade reduces working volume, not the warm-up.
- **Core and the per-muscle weekly floors are NOT scaled.** `core_week_spec` and `muscle_floors` are blocking render errors and they are not tier-scoped: a Tier C plan carries its full core and direct-set floors or it does not render. The cut comes out of the rest of the accessory block. Only a full-block deload (`load_policy` `reduce`: Tier A / B) demotes them; a single cadence deload session does not.

The workout markdown looks like a normal session at a smaller size:

```markdown
# Workout plan — <date>
> Today's call: <session_recommendation.headline>
> Why: <rationale[0].note>
>      <rationale[1].note>

Assessment: ./<date>-assessment.html

## Workout 1: UPPER A + CORE
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- Jumping Jacks: 50
- Arm Circles: 20
- Dumbbell Flat Bench Press: 25kgx5 (warmup) /// 35kgx3 (warmup) /// 50kgx8-10 /// 50kgx8-10 /// 50kgx8-10
- Shoulder Press Machine: 45kgx8-10 /// 45kgx8-10
- Cable Lat Pulldown: 60kgx8-10 /// 60kgx8-10
- Cable Lateral Raise: 10kgx12-15 /// 10kgx12-15
- Kneeling Cable Crunch: 20kgx12-15 /// 20kgx12-15
- Cable Overhead Tricep Extension: 35kgx10-12 /// 35kgx10-12
- Cable Face Pull: 20kgx12-15 /// 20kgx12-15
```

What the example shows on purpose: a 24-set base scaled to about 14 working sets (15 here), every set written as its own `///` entry (a bullet reading `Cable Lateral Raise: 10kgx12-15` is ONE set), the loads and ranges copied from `next_dose` rather than held, `UPPER A` classifying as an upper day with 2 core sets inside the cable block, and the session closing on a face pull, which is neither core nor arms.

If the gate fired Tier C because of a specific over-MRV muscle, also rotate the affected exercise to a different movement pattern (e.g. if chest is over MRV, swap flat bench to incline DB for this session).

---

## Tier D — `normal_strength` (green)

Run the full Phase 2 programming rules. The substitute template is empty — the existing per-workout templating in SKILL.md is the spec.

---

## Tier E — `normal_strength` + taper warning

Normal session, with one-line warning at the top of the markdown:

```markdown
# Workout plan — <date>
> Today's call: <session_recommendation.headline>

Assessment: ./<date>-assessment.html

Fitness is bleeding off if this continues.

## Workout 1: <…>
[normal Phase 2 templating]
```

---

## Override behavior

Two ways in, one path:

- **Tier A or B**: the user picked option 3 ("normal strength anyway") when asked.
- **Tier C**: the user explicitly asks to train normally after seeing the call ("ignore the downgrade, plan normally").

Either way:

1. Regenerate the tracker JSON with `read_tracker.py --override-gate`. It rewrites the gate to Tier D (`green`, full set budget) and keeps the original call in `override_message` and the first `rationale` entry.
2. Write `coach_reads.json` against that JSON, then plan a normal Tier D block with the full Phase 2 rules. Do not hand-strip a restriction from a JSON that still carries it: the checks would judge the plan against the old tier.
3. Open the markdown with a visible note so the next session can see it: `> OVERRIDE: gate recommended Tier <X> (<label>); user chose normal strength.` followed by the original rationale notes.

Default behavior is to honor the gate's call on Tier C and to ask on Tier A and B. Never override on assumption.
