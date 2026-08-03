# Substitute protocols — what to write when the gate refuses strength

When `session_recommendation.tier` is **A**, **B**, or **C**, the coach does NOT write the planned strength session as-is. Instead, the workout markdown is filled from one of the templates below. The substitute's `kind` field tells you which template to use.

Reasoning behind the gate is in the Phase 2 preamble of `SKILL.md`. The thresholds and per-tier triggers are in `lib/constants.py:SESSION_GATE_THRESHOLDS`. The decision lives in `lib/health.py:compute_session_recommendation`.

**The templates below are copy-me markdown and `validate_workout_md` runs over the result.** Its em-dash rule allows one only on the `# Workout plan — <date>` title line and on an indented `  — cue` sub-bullet. A `> Today's call:` or `> Why:` line is neither, so an em-dash there is a blocking error and the render exits 2. Use a period, comma, semicolon or colon when you fill these in.

---

## Tier A — `rest` (illness / acute under-recovery)

The data says rest. Refuse to write strength. The workout markdown is short.

```markdown
# Workout plan — <date>
> Today's call: Rest today.
> Why: <rationale[0].note>
>      <rationale[1].note>
>      <rationale[2].note>

Assessment: ./<date>-assessment.html

## Rest day
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- 20-min easy walk (RPE 2–3, conversational pace)
- Hydration: front-load fluids today
- Sleep priority: 8h target tonight, no caffeine after noon

## Re-evaluate tomorrow
Date: ___

- Check wrist temp, RHR, HRV in the morning before deciding next session
- If wrist temp returns to baseline AND RHR drops AND HRV is back in the 60-day band, the next planned session is back on
```

**Do not** add strength alternatives. **Do not** offer "if you feel better, do X". The user can override explicitly; the default is rest.

---

## Tier B — `zone_2` (HRV crash / TSB high fatigue / WoW spike)

Zone 2 cardio + light mobility, no strength.

```markdown
# Workout plan — <date>
> Today's call: Zone 2 day, not strength.
> Why: <rationale[0].note>
>      <rationale[1].note>

Assessment: ./<date>-assessment.html

## Zone 2 cardio + mobility
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- Zone 2 cardio: 45–60 min at ~<estimated_max_hr × 0.65> bpm
  — bike / outdoor walk-jog / rower — choose by what's accessible
  — talk-test pace: full sentences without gasping
- Mobility: 15 min
  — hip 90/90, thoracic open-book, ankle dorsiflexion, shoulder CARs
- Optional: sauna 15 min ≥80°C (if available)

## Re-evaluate tomorrow
- If HRV returns to baseline and TSB lifts, strength is back on
```

---

## Tier B — `reactive_deload_week` (MRV breach / stalled lifts / unmarked deload)

A full week of deloading. The markdown lists the deload sessions for the whole week, not one day.

```markdown
# Workout plan — <date>
> Today's call: Reactive deload this week.
> Why: <rationale[0].note>
>      <rationale[1].note>

Assessment: ./<date>-assessment.html

## Deload Session 1
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- <Compound 1>: <last working weight>x<last reps>, <halved set count>
  — hold load, halve sets
- <Compound 2>: <last working weight>x<last reps>, <halved set count>
- <Accessory 1>: <last weight>x<last reps>, <halved set count>
- <Accessory 2>: <last weight>x<last reps>, <halved set count>

## Deload Session 2
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- <…>

## Deload Session 3
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- <…>

## Notes
- Conditioning finisher dropped from every session this week
- Rotate <over-MRV muscle> exercises to a different movement pattern (e.g. flat bench → incline DB if chest is the over-MRV muscle)
- Return to normal volume next week if `recovery.score ≥ 6` and HRV trend back in band
```

The user's session count for the week (the `/coach plan N sessions` arg) controls how many `## Deload Session N` blocks you write.

---

## Tier C — `modified_strength` (downgrade)

Same session pattern as the planned workout, but with the modifications baked in:

- **Volume**: −25% on secondary / isolation exercises (halve isolations; keep compounds at planned volume)
- **Loads**: hold every working weight (compounds, accessories, isolation, core — all of it)
- **Finisher**: drop the conditioning finisher entirely
- **PR attempts**: not allowed
- **Warm-up**: unchanged — keep the two prep movements and the ramp sets into the first heavy compound. A recovery downgrade reduces working volume, not the warm-up.
- **Core and direct arms are NOT halved.** `core_week_spec` and `arm_week_spec` are blocking render errors and they are not tier-scoped: a Tier C plan carries its full core and arm dose or it does not render. The isolation cut comes out of the rest of the accessory block. Only an explicit deload (Tier B, or a prescribed deload session) reduces them.

The workout markdown looks like a normal session but with the held loads explicit:

```markdown
# Workout plan — <date>
> Today's call: Modified strength. Hold loads, cut accessories.
> Why: <rationale[0].note>
>      <rationale[1].note>

Assessment: ./<date>-assessment.html

## Workout 1: PUSH
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- Jumping Jacks: 50
- Arm Circles: 20
- Dumbbell Flat Bench Press: 25kgx5 (warmup) /// 35kgx3 (warmup) /// 50kgx8 /// 50kgx8
  — hold last session's load
- Incline Chest Press Machine: 50kgx10 /// 50kgx10
- Cable Lateral Raise: 12kgx12 /// 12kgx12
- Kneeling Cable Crunch: 20kgx12 /// 20kgx12
- Cable Tricep Pushdown: 35kgx12 /// 35kgx12
- (no finisher this session)
```

Two things the example is showing on purpose. The halved isolations are still written as one `///` token per set: a bullet reading `Cable Lateral Raise: 12kgx12` is ONE set, so writing two sets that way silently halves them again. And `PUSH` classifies as an upper day, so its core allocation is 2 sets, sitting inside the cable block rather than at the end.

If the gate fired Tier C because of a specific over-MRV muscle, also rotate the affected exercise to a different movement pattern (e.g. if chest is over MRV, swap flat bench → incline DB for this session).

---

## Tier D — `normal_strength` (green)

Run the full Phase 2 programming rules. The substitute template is empty — the existing per-workout templating in SKILL.md is the spec.

---

## Tier E — `normal_strength` + taper warning

Normal session, with one-line warning at the top of the markdown:

```markdown
# Workout plan — <date>
> Today's call: Train as planned, but TSB is over +10 right now. You've been over-recovered. Fitness is bleeding off if this continues.

Assessment: ./<date>-assessment.html

## Workout 1: <…>
[normal Phase 2 templating]
```

---

## Override behavior

If the user explicitly requests an override ("ignore the rest call, plan strength anyway"), the coach can generate the planned strength session BUT must:

1. Open the markdown with a visible note: `> OVERRIDE: gate recommended <tier label>; user requested strength anyway.`
2. Apply the Tier C modifications (−25% volume on secondaries, hold loads, no finisher) **regardless** — the override is for the session type, not the load discipline.
3. Cite the rationale signals in the note so the next session can reference them.

Default behavior is to honor the recommendation. Never override on assumption.
