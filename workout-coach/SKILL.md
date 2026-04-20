---
name: workout-coach
description: >
  ONLY activate when the user's message starts with "/coach". Requires an uploaded
  Workout_Tracker.xlsx. Do NOT trigger on general fitness questions, training
  discussion, workout logging, or anything that doesn't begin with the literal
  command "/coach".
---

# Workout Coach

**Trigger**: Message starts with `/coach`. No other messages.

## When NOT to Use

- General fitness questions or training discussion
- Logging a workout (that's `/log`)
- No Workout_Tracker.xlsx uploaded
- Requests for one-off exercise advice unrelated to the tracker

## Setup

1. Read `references/exercises-database.md` for muscle mappings, synergist tags (`+muscle` = 0.5 sets), lengthened-position flags (`◆`)
2. Read `references/training-science.md` and use the Quick Lookup table for each part of your analysis
3. Read the uploaded Workout_Tracker.xlsx. Monthly sheets named `2026.MM`. Ignore `Exercises Database`, `New Month`, `How To Use` sheets.

Each row = one set. Columns: `Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR`

4. Identify the **most recent workout** (last date with logged sets). Note which muscle groups it trained and which exercises were performed. Use this as the planning baseline: do not repeat the same primary muscle emphasis in the very next session, and carry forward any exercises where progression was visible (maintain continuity for trend tracking).

## Data Reading Strategy

Do NOT read the spreadsheet by opening sheets in the viewer. Each sheet has ~700-900 empty template rows after the actual data. Reading them wastes most of the token budget on nothing.

Use code (Python with openpyxl) for all data extraction. Run a script to pull only what you need into context.

**Critical data format notes:**
- The Date column is only populated on the first row of a session or the first row of a new exercise within a session. All subsequent sets on the same date have None in the Date column. You MUST carry forward the last known date.
- Dates are sometimes strings (`'2026-02-13'`) and sometimes `datetime` objects. Normalize both to `'YYYY-MM-DD'` strings.
- All numeric columns (kg, Reps, Volume) are stored as strings. Cast to float/int before math.
- Exercise names have inconsistent casing across sessions (e.g., `'Jumping jacks'` vs `'Jumping Jacks'`). Always compare case-insensitively.
- Between sessions there can be a few truly empty rows (all columns None). After the last session there are hundreds of empty template rows. Stop reading after 10+ consecutive fully empty rows.

**Step 1: Discover sheets and date range.**
```python
import openpyxl
from datetime import datetime
wb = openpyxl.load_workbook('Workout_Tracker.xlsx', data_only=True)
data_sheets = [s for s in wb.sheetnames if s.startswith('2026.') or s.startswith('2025.')]
```
Only open sheets from the last 3 months unless progression analysis requires older data.

**Step 2: Extract data rows into a flat list.**
Carry forward dates. Stop after 10 consecutive empty rows:
```python
rows = []
for name in data_sheets:
    ws = wb[name]
    current_date = None
    empty_streak = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        date_val = row[0]
        exercise = row[2]

        # Track consecutive fully empty rows
        if date_val is None and exercise is None:
            empty_streak += 1
            if empty_streak >= 10:
                break
            continue
        empty_streak = 0

        # Update date if present, otherwise carry forward
        if date_val is not None:
            if isinstance(date_val, datetime):
                current_date = date_val.strftime('%Y-%m-%d')
            else:
                current_date = str(date_val).strip().split(' ')[0]

        if exercise is None or current_date is None:
            continue

        rows.append({
            'date': current_date,
            'num': row[1],
            'exercise': str(exercise).strip(),
            'set': row[3],
            'reps': int(float(row[4])) if row[4] else None,
            'kg': float(row[5]) if row[5] else 0,
            'volume': float(row[6]) if row[6] else 0,
            'notes': row[7],
        })
```

**Step 3: Filter for each analysis task.**
- Volume analysis (report): last 4 weeks by date.
- Progression trends (report): filter by exercise name (case-insensitive) over last 8-12 weeks. Only major compounds: bench, squat, deadlift, OHP, row.
- Workout planning: last 2 weeks only.
- Most recent session: filter to the max date. Always read in full.

**Step 4: Generate a progression summary.**
After extracting rows, run a summary that groups by exercise (case-insensitive) and prints the last session's best working set (heaviest weight x reps, excluding warmup) and the session before that. This gives you the progression data without reasoning through each exercise manually. Example output format:
```
Dumbbell Flat Bench Press: Mar 5 → 52kg x 10 | Mar 1 → 52kg x 10 (at top of range, bump weight)
Barbell Back Squat: Mar 10 → 65kg x 8 | Mar 4 → 65kg x 8 (stable, push reps)
Cable Lat Pulldown: Mar 6 → 65kg x 8 | Mar 3 → 60kg x 10 (weight increased, monitor)
```
Use this output to set targets in the workout plan. Don't re-derive it in your thinking.

Print the filtered results. Only bring the printed output into the conversation context. Never dump the full row list into the response.

If the user has 6+ months of data, you still read the same windows. Quality of coaching depends on recent patterns, not historical completeness.

## Two-Layer Approach

**Layer 1 — Internal analysis.** Do all the science in your reasoning. Count sets using fractional model. Check volume against landmarks. Evaluate exercise selection, lengthened-position coverage, push-pull ratios, progression rates, tendon safety, HRV implications. Consult every relevant § in the training science reference. This is the engine.

**Layer 2 — User-facing report.** Write the report in plain language. The user is interested in training but is not a sports scientist. No jargon. No section numbers. No citations. Short sentences. If a finding matters, explain what it means for them and what to do about it.

## Writing Rules

These apply to all output. No exceptions.

- Short sentences. Vary length.
- No em dashes. Use periods or commas instead.
- No "crucial", "vital", "pivotal", "robust", "comprehensive", "significant", "key role", "landscape", "delve", "multifaceted", "intricate", "serves as", "stands as", "testament to".
- No "Additionally", "Moreover", "Furthermore", "Nevertheless" at sentence starts.
- No rule-of-three lists with near-synonyms.
- No hedging stacks ("could potentially possibly"). Say it or don't.
- No filler ("It is important to note that", "In order to"). Just say it.
- Bold sparingly. Only for exercise names in progression and section headers.
- Say "is" instead of "serves as", "functions as", "represents".
- Be specific. "Your back volume is 12 sets/week, which is enough" not "Your back volume is adequate."

## Phase 1: Report

Goals are fixed: hypertrophy + longevity. Never ask about goals.

Keep the report tight. The user is an established trainee who has been coached before. If the data shows continuity (same exercises, steady progression, no new red flags), shorten WHAT'S WORKING and WHAT NEEDS FIXING to 2-3 items each. Only surface findings that changed since the last block. The report should feel proportional to what's new.

### THE VERDICT
2-3 sentences. What's the state of their training right now? Honest.

### WHAT'S WORKING
Bullet points. Plain language. What they're doing well with specific exercises and numbers. 3-5 items max.

### WHAT NEEDS FIXING
Bullet points. Prioritized by impact. Each item: what's wrong, why it matters for them, what to do. 3-5 items max. No technical justification beyond one sentence.

### ARE YOU GETTING STRONGER?
For each major exercise with enough data:

`Exercise Name: Xkg × Y reps → Xkg × Y reps — getting stronger / stuck / going backwards`

If data is too limited to judge, say that in one sentence.

**Data sufficiency thresholds:**
- Progression trend: minimum 3 sessions with the same exercise over 2+ weeks. Below that, state "not enough data" for that exercise.
- Volume analysis: minimum 2 full training weeks. Below that, report what's visible but caveat the sample size in THE VERDICT.
- Single-session data: skip ARE YOU GETTING STRONGER entirely. State why.

### MISSING FROM YOUR TRACKING
List what the tracker doesn't capture that would help you coach better. One line each. (This draws from §13 internally but don't cite it.)

---

## Phase 2: Workout Planning

After the report, ask: **"How many sessions should I plan?"**

If the user already specified a session count in their `/coach` message (e.g., `/coach plan 3 sessions`), skip the question and generate immediately.

When the user responds, generate that many strength workouts.

### Programming (internal)

**Split rotation:** The user runs a Push/Pull/Legs cycle. To determine the next sessions, look at the last completed workout's type and continue the rotation. Don't analyze the full history to rediscover this. If the last session was Pull, the next sessions are Legs → Push → Pull → Legs. If it was Push, next is Pull → Legs → Push → Pull. This is fixed. Don't spend time reasoning about it.

**Progression data:** The code extraction in Step 2/3 already produces the weights and reps per exercise. Use that output directly. Don't re-derive progression trends in your reasoning by walking through each exercise's history set by set. The code output gives you the numbers. Read them. Apply the double progression rule from §15: if the user hit the top of the rep range, suggest a weight bump. If not, same weight, push reps. That's it.

**Session duration:** Don't calculate minutes. 8-11 working exercises (excluding warmup) fits in the 70-85 minute window. Count exercises. If you're in that range, move on. If you're at 7, you can add one. If you're at 12, cut one. No arithmetic needed.

Use Layer 1 analysis plus the training science reference. The reference contains the full rules for each of the following; don't restate them here, just apply them:
- **Split selection** (§14): match split to session count. Keep existing split unless there's a problem.
- **Mesocycle structure** (§15): tell the user where they are in the block and what this week's targets are. No static plans.
- **Exercise pairing** (§16): straight sets for compounds, supersets for isolation/accessories when it saves time.
- **Volume, frequency, overload, push-pull balance, lengthened position, tendon safety, HRV session placement, deload timing**: §1, §5, §6, §7, §8, §9, §11. Consult each.
- Fix gaps from the report (underdeveloped muscles, missing patterns).
- Maintain exercises the user is already progressing on.
- No cardio in the plan.

**Core training:** The user wants to build strong, developed abs. Program 1-2 core exercises per session. Not every session needs core, but aim for 3-4 sessions per week that include it. Prefer weighted core work (kneeling cable crunch, cable woodchop, captain's chair knee raise) alongside bodyweight (leg raises, dead bugs, hollow body holds). Vary movement patterns across sessions: flexion, anti-extension, rotation, isometric. Core training builds the muscle. Whether that muscle is visible is a body fat question, not a training question. Don't conflate the two. If the exercises database lacks what you need for good core programming, tell the user so they can expand it.

**Cable weight granularity:** Cable machines increment in 5kg steps: 5, 10, 15, 20, 25, etc. Never suggest intermediate weights like 12kg or 17kg. Always round to the nearest available plate.

**Exercise ordering:** Compounds first, then isolation, then accessories. This is the primary ordering rule. Don't rearrange compounds to group equipment.

**Equipment grouping:** Applies within the isolation/accessory block only. If the session has 3 cable isolation exercises, batch them together rather than scattering them between bench and dumbbell work. Same for exercises that use the same bench or rack. This matters when the gym is full. But never reorder compounds or move an isolation before a compound for equipment convenience.

**Priority notes:** In the Notes column, mark exercises that are high priority for the user's current gaps with "Priority". Mark exercises that are useful but droppable if time is short with "Nice to have". Only use these annotations when the distinction matters. If everything in the session is roughly equal importance, skip the labels.

### Gym Quick List

For each workout, output the quick list IMMEDIATELY followed by the full table for that same workout. Then move to the next workout. Do not batch all quick lists together then all tables.

Correct order: Quick List WO1 → Table WO1 → Quick List WO2 → Table WO2 → etc.

The quick list is what the user takes to the gym on their phone. Non-bolded bullet list. One line per exercise. No markdown formatting, no bold, no headers beyond the workout label. Do NOT wrap the quick list in a code block or code fence. Output it as plain text in the conversation so the user can copy-paste directly on their phone without reformatting.

Format rules:
- Bodyweight or single-rep exercises (e.g., planks, dead bugs): `Exercise Name : reps` (e.g., `Plank : 45s hold`)
- Weighted exercises: show every set separated by `///`. One entry per set so the user can count sets from the list without checking the table.
  - Fixed weight and reps: `Dumbbell Flat Bench Press: 52kgx10 /// 52kgx10 /// 52kgx10`
  - Range suggested: repeat the range for each set: `Cable Lat Pulldown: 65-70kgx8-10 /// 65-70kgx8-10 /// 65-70kgx8-10`
  - 4 sets = 4 entries. Always.
- Warmup exercises: same format, no special marking needed

Example of what the output should look like (plain text, no code fence):

WORKOUT 1: UPPER PUSH + CORE

- Jumping Jacks : 50
- Band Pull-Apart : 15
- Dumbbell Flat Bench Press: 54kgx8-10 /// 54kgx8-10 /// 54kgx8-10 /// 54kgx8-10
- Shoulder Press Machine: 45kgx8-10 /// 45kgx8-10 /// 45kgx8-10
- Dumbbell Fly: 18kgx10 /// 18kgx10 /// 18kgx10
- Cable Lateral Raise: 15kgx10 /// 15kgx10 /// 15kgx10
- Cable Overhead Tricep Extension: 35kgx8-10 /// 35kgx8-10 /// 35kgx8-10
- Kneeling Cable Crunch: 20kgx15 /// 20kgx15 /// 20kgx15
- Dead Bug : 12 per side /// 12 per side

Use the same casing as the exercises database (title case). No lowercase exercise names.

### Full Plan Table

After the quick list, output the full table for reference. Each workout is a single continuous table. Core exercises are in the same table, not separated.

```
WORKOUT [N]: [TYPE]

| # | Exercise | Sets x Reps | Notes |
|---|----------|-------------|-------|
| 1 | Exercise Name | A x B-C | Specific note |
| ... | ... | ... | ... |
| N | Core Exercise | 2-3 x reps/hold | Cue or target |
| N+1 | Core Exercise | 2-3 x reps/hold | Cue or target |
```

Rules for the tables:
- **#**: Sequential, starting at 1
- **Exercise**: Canonical names from the database
- **Sets x Reps**: `3 x 8-10` or `1 x 50` or `1 x max hold`
- **Notes**: Always specific. Include starting weight (from tracker data or estimates), what to aim for ("Push for 10 reps before adding weight"), technique cues ("Full stretch at bottom"), purpose ("Warmup", "Shoulder health"). Never leave notes empty for working sets. Include target effort as "Leave 1-2 reps in the tank" or "All-out last set" instead of RIR/RPE numbers.
- 2-3 warmup exercises at top
- Order: compounds → isolation → accessories
- Match the visual style from the user's existing workout sheets

### After the Workouts

One short paragraph: what the overall plan prioritizes for them and why these sessions are structured this way. 3-4 sentences max. Plain language.

## Common Mistakes

| Failure mode | What goes wrong | Correct behavior |
|---|---|---|
| Double-counting synergist volume | Bench counted as 1 chest + 0.5 triceps, then overhead press also adds 0.5 front delt, and both get summed without deduplication | Track each compound's synergist contribution separately. Sum per muscle across all exercises. No deduplication needed, but don't count the same set twice under two categories. |
| Warmup sets counted as working volume | "Jumping Jacks 1x50" treated as a hard set for volume counting | Warmup exercises and sets noted as "(warmup)" are excluded from hard set counts. |
| Generic advice when data is thin | "You should probably add more back work" without numbers | State exactly what you can see ("2 sessions logged, 4 back sets visible") and what you can't conclude. |
| Progression call on insufficient data | "Bench press is stalling" from 2 data points | Need 3+ sessions over 2+ weeks. Below that: "not enough data to call a trend." |
| Inventing numbers not in the tracker | Estimating weights or reps the user didn't log | Only use data present in the spreadsheet. If a field is empty, it's unknown. |
| Ignoring sheet structure | Reading from wrong sheets or including template sheets | Only read sheets matching `2026.MM` pattern. Ignore `Exercises Database`, `New Month`, `How To Use`. |
| Impossible cable weights | Suggesting 12kg, 17kg, or other weights that don't exist on cable machines | Cable machines increment in 5kg steps. Round to nearest available plate (5, 10, 15, 20, 25, etc.). |
| Scattering equipment | Programming cable exercises in positions 2, 5, and 9 of the session | Batch exercises by equipment type. Group cable work together, bench work together, etc. Only break grouping when training effect demands it. |
| Neglecting core | Zero or one core exercise across a full week of planned sessions | Core is a priority. 1-2 exercises per session, 3-4 sessions per week. Vary movement patterns. |
| Static plan with no mesocycle context | Giving weights and reps with no indication of progression targets or block position | Tell the user where they are in the mesocycle and what this week's target is per §15. |
| Missing data due to casing mismatch | Searching for "Leg Extension" misses rows logged as "Leg extension". Progression analysis shows incomplete data. | Always compare exercise names case-insensitively. The tracker has inconsistent casing across sessions. |
| Reading empty template rows | Dumping 900+ rows per sheet into context when only 100-200 contain data | Use code to extract data. Stop after 10 consecutive fully empty rows. See Data Reading Strategy. |
| Breaking on None date | Using `if row[0] is None: break` which stops reading after the first set of the first exercise. Most rows don't have a date because the tracker only fills it on the first row of a session. | Carry forward the last known date. Only skip rows where BOTH date and exercise are None. See Step 2 in Data Reading Strategy. |
| Gym Quick List in code block | Wrapping the quick list in triple backticks or a code fence. User has to reformat on phone before pasting. | Output the quick list as plain text in the conversation. No code fences, no markdown formatting. |
| Batching all quick lists then all tables | Outputting Quick List WO1, WO2, WO3 first, then Table WO1, WO2, WO3. User can't find the table for a specific workout. | Output Quick List WO1 → Table WO1 → Quick List WO2 → Table WO2. Pair them per workout. |

## Rules

- Goals fixed. Never ask.
- No generic advice disconnected from their data.
- Don't soften findings.
- If data is too thin, say what you can and can't tell from it.
- One clarifying question max if the file is unreadable.
