# Substitute protocols — what to write when the gate restricts strength

When `session_recommendation.tier` is **A**, **B**, or **C**, the coach does NOT write the planned strength session as-is.

- **Tier C** is automatic: fill the markdown from the Tier C template below.
- **Tier A and B are never decided alone.** Stop after `read_tracker`, before writing `coach_reads.json` or the plan, and ask the user in chat (protocol below). Fill the markdown from the template for the option they choose.

Reasoning behind the gate is in the Phase 2 preamble of `SKILL.md`. The thresholds and per-tier triggers are in `lib/constants.py:SESSION_GATE_THRESHOLDS`. The decision lives in `lib/health.py:compute_session_recommendation`.

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
2. **Lighter strength**: fewer sets, held weights. Use the lighter-strength template below, against the tracker JSON as it is. On `reactive_deload` the set budget is half the base, and `check_plan.py` judges each session against it. **On Tier A the set budget is 0, which the budget check reads as "no budget" and skips**, so nothing checks the set count: halve the sets yourself and say in the chat summary that the budget check did not run. On Tier A and on `reactive_deload` the core and arm VOLUME floors drop to warnings (it is a declared deload), while diversity and placement stay blocking.
3. **Normal strength anyway**, for example planned for the following week. Regenerate the tracker JSON with `read_tracker.py --override-gate`, then follow "Override behavior" at the end of this file.

Do not suggest a default beyond the gate's own call, and do not write any file until the user has answered.

---

## Option 1 — Rest day

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

- Hydration: front-load fluids today
- Sleep priority: 8h target tonight, no caffeine after noon

## Re-evaluate tomorrow
Date: ___

- Check wrist temp, RHR, HRV in the morning before deciding next session
- If wrist temp returns to baseline AND RHR drops AND HRV is back in the 60-day band, the next planned session is back on
```

**Do not** add strength alternatives or any cardio. **Do not** offer "if you feel better, do X". The user already chose rest.

---

## Option 2 — Lighter strength (reactive-deload week)

Fewer sets, held weights. The markdown lists the lighter sessions for the whole week, not one day.

```markdown
# Workout plan — <date>
> Today's call: Lighter strength this week. Fewer sets, held weights.
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

The user's session count for the week (the `/coach plan N sessions` arg) controls how many `## Deload Session N` blocks you write. Every set is still its own `///` entry; the `<halved set count>` placeholder above means writing that many entries.

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
> Today's call: Train as planned, but TSB has been over +10 for 5+ days. You've been over-recovered. Fitness is bleeding off if this continues.

Assessment: ./<date>-assessment.html

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
