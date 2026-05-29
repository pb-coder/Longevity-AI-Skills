# Substitute protocols — what to write when the gate refuses strength

When `session_recommendation.tier` is **A**, **B**, or **C**, the coach does NOT write the planned strength session as-is. Instead, the workout markdown is filled from one of the templates below. The substitute's `kind` field tells you which template to use.

Reasoning behind the gate is in the Phase 2 preamble of `SKILL.md`. The thresholds and per-tier triggers are in `lib/constants.py:SESSION_GATE_THRESHOLDS`. The decision lives in `lib/health.py:compute_session_recommendation`.

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
Date: ___
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
Date: ___
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
Date: ___
Recovery: sauna ___ / cold ___ / rlt ___

- <Compound 1>: <last working weight> × <last reps>, <halved set count>
  — hold load, halve sets
- <Compound 2>: <last working weight> × <last reps>, <halved set count>
- <Accessory 1>: <last weight> × <last reps>, <halved set count>
- <Accessory 2>: <last weight> × <last reps>, <halved set count>

## Deload Session 2
Date: ___
Recovery: sauna ___ / cold ___ / rlt ___

- <…>

## Deload Session 3
Date: ___
Recovery: sauna ___ / cold ___ / rlt ___

- <…>

## Notes
- Conditioning finisher dropped from every session this week
- Rotate <over-MRV muscle> exercises to a different movement pattern (e.g. flat bench → incline DB if chest is the over-MRV muscle)
- Return to normal volume next week if `recovery.score ≥ 6` and HRV trend back in band
```

The user's session count for the week (the `/coach plan N sessions` arg) controls how many `## Deload Session N` blocks you write.

---

## Tier B — `mobility_sauna` (variant, rare — used when HRV is crashed but TSB / load are fine)

Lower stimulus than Zone 2, focused on parasympathetic recovery.

```markdown
# Workout plan — <date>
> Today's call: Mobility + sauna only.
> Why: <rationale[0].note>

Assessment: ./<date>-assessment.html

## Mobility + sauna
Date: ___
Recovery: sauna ___ / cold ___ / rlt ___

- Mobility flow: 30 min
  — hip 90/90, thoracic rotations, shoulder dislocates, ankle rocks, deep squat hold
  — RPE 2–3, no breath-holds, no force
- Sauna: 15–20 min at ≥80°C if available (heat-shock-protein band)
- Sleep priority tonight, hydration through the day

## Re-evaluate tomorrow
- HRV recovery first, then strength can come back
```

---

## Tier C — `modified_strength` (downgrade)

Same session pattern as the planned workout, but with the modifications baked in:

- **Volume**: −25% on secondary / isolation exercises (halve isolations; keep compounds at planned volume)
- **Loads**: hold every working weight (compounds, accessories, isolation, core — all of it)
- **Finisher**: drop the conditioning finisher entirely
- **PR attempts**: not allowed

The workout markdown looks like a normal session but with the held loads explicit:

```markdown
# Workout plan — <date>
> Today's call: Modified strength — hold loads, cut accessories.
> Why: <rationale[0].note>
>      <rationale[1].note>

Assessment: ./<date>-assessment.html

## Workout 1: PUSH
Date: ___
Recovery: sauna ___ / cold ___ / rlt ___

- Dumbbell Flat Bench Press: 50 kg × 8 /// 50 kg × 8
  — hold last session's load
- Incline Chest Press Machine: 50 kg × 10 /// 50 kg × 10
- Cable Lateral Raise: 12 kg × 12  *(halved from 3 sets to 2)*
- Triceps Pushdown: 35 kg × 12  *(halved from 3 sets to 2)*
- (no finisher this session)
```

If the gate fired Tier C because of a specific over-MRV muscle, also rotate the affected exercise to a different movement pattern (e.g. if chest is over MRV, swap flat bench → incline DB for this session).

---

## Tier D — `normal_strength` (green)

Run the full Phase 2 programming rules. The substitute template is empty — the existing per-workout templating in SKILL.md is the spec.

---

## Tier E — `normal_strength` + taper warning

Normal session, with one-line warning at the top of the markdown:

```markdown
# Workout plan — <date>
> Today's call: Train as planned — but TSB has been over +10 for 5+ days. You've been over-recovered. Fitness is bleeding off if this continues.

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
