---
name: workout-coach
description: >
  Use when the user's message starts with "/coach". Do NOT trigger on general
  fitness questions, training discussion, logging, or requests unrelated to the
  workout tracker.
---

# Workout Coach

**Trigger**: Message starts with `/coach`. No other messages.

## When NOT to Use

- General fitness questions or training discussion
- Logging a workout (that's `/log`)
- Requests for one-off exercise advice unrelated to the tracker

## Setup

1. Read `references/exercises-database.md` for muscle mappings, synergist tags (`+muscle` = 0.5 sets), lengthened-position flags (`◆`).
2. Read `references/training-science.md` and use the Quick Lookup table for each part of your analysis.
3. Read `./Workout Tracker.xlsx` from the current working directory. If it's not there, stop and say so in one line. Don't search the filesystem. Monthly sheets are named `YYYY.MM`; ignore `Exercises Database` and any `New Month` / `How To Use` templates if present.

Each row = one set. Columns: `Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR`.

4. Identify the **most recent workout** (last date with logged sets). Note which muscle groups it trained and which exercises were performed. Use this as the planning baseline: do not repeat the same primary muscle emphasis in the very next session, and carry forward any exercises where progression was visible. The rest of each session's slots are where variation lives — see §17.

## Output target

All user-facing output — the report AND the plan — goes into `./workout_plan.md`, overwriting whatever was there. The chat gets one short block: a one-line verdict plus `Wrote plan to workout_plan.md (N sessions)`. Nothing else.

The file structure:

```
# Workout plan — <YYYY-MM-DD>

## Report
### The verdict
### What's working
### What needs fixing
### Are you getting stronger?
### Missing from your tracking

## Plan

### Workout 1: <TYPE>
<quick list — plain bullets, one line per set>

| # | Exercise | Sets × Reps | Notes |
| - | -------- | ----------- | ----- |
...

### Workout 2: <TYPE>
...

## Why this plan
<3-4 sentences>
```

Write the file in one pass at the end. Don't stream sections to chat while thinking.

## Data Reading Strategy

The monthly sheets keep a buffer of empty rows after the last logged set (roughly 2 rows on past months, ~50 on the current month after `/maintain` trims). Read with openpyxl and stop after 10 consecutive fully empty rows — don't dump raw sheet contents into context.

**Critical data format notes:**
- Dates are usually `'YYYY-MM-DD'` strings. Older rows may be `datetime` objects or have None (carry forward the last known date defensively — the current tracker fills every row, but historical data wasn't always that way).
- Numeric columns (kg, Reps, Volume) are often strings. Cast to float/int before math.
- Exercise names have inconsistent casing across sessions (e.g., `'Jumping jacks'` vs `'Jumping Jacks'`). Always compare case-insensitively.
- Between sessions there can be a few truly empty rows. After the last real session there are hundreds. Stop after 10+ consecutive fully empty rows.

**Step 1: Discover sheets and date range.**
```python
import openpyxl
from datetime import datetime
wb = openpyxl.load_workbook('Workout Tracker.xlsx', data_only=True)
import re
data_sheets = [s for s in wb.sheetnames if re.match(r'^\d{4}\.\d{2}$', s)]
```
Only open sheets from the last 3 months unless progression analysis requires older data.

**Step 2: Extract data rows into a flat list.**
Carry forward dates defensively. Stop after 10 consecutive empty rows:
```python
rows = []
for name in data_sheets:
    ws = wb[name]
    current_date = None
    empty_streak = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        date_val = row[0]
        exercise = row[2]

        if date_val is None and exercise is None:
            empty_streak += 1
            if empty_streak >= 10:
                break
            continue
        empty_streak = 0

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
After extracting rows, run a summary that groups by exercise (case-insensitive) and prints the last session's best working set (heaviest weight × reps, excluding warmup) and the session before that. Example:
```
Dumbbell Flat Bench Press: Apr 5 → 52kg x 10 | Apr 1 → 52kg x 10 (at top of range, bump weight)
Barbell Back Squat: Apr 10 → 65kg x 8 | Apr 4 → 65kg x 8 (stable, push reps)
Cable Lat Pulldown: Apr 6 → 65kg x 8 | Apr 3 → 60kg x 10 (weight increased, monitor)
```
Use this output to set targets in the plan. Don't re-derive it in your thinking.

Print the filtered results for your own use. The raw row list never goes into the response or the file.

If the user has 6+ months of data, you still read the same windows. Coaching quality depends on recent patterns, not historical completeness.

## Two-Layer Approach

**Layer 1 — Internal analysis.** Do all the science in your reasoning. Count sets using the fractional model. Check volume against landmarks. Evaluate exercise selection, lengthened-position coverage, push-pull ratios, progression rates, tendon safety, HRV implications. Consult every relevant § in the training science reference. This is the engine.

**Layer 2 — The file.** Write `workout_plan.md` in plain language. The user trains seriously but is not a sports scientist. No jargon. No section numbers. No citations. Short sentences. If a finding matters, explain what it means for them and what to do about it.

## Writing Rules

These apply to everything written into `workout_plan.md`. No exceptions.

- Short sentences. Vary length.
- No em dashes. Use periods or commas instead.
- No "crucial", "vital", "pivotal", "robust", "comprehensive", "significant", "key role", "landscape", "delve", "multifaceted", "intricate", "serves as", "stands as", "testament to".
- No "Additionally", "Moreover", "Furthermore", "Nevertheless" at sentence starts.
- No rule-of-three lists with near-synonyms.
- No hedging stacks ("could potentially possibly"). Say it or don't.
- No filler ("It is important to note that", "In order to"). Just say it.
- Bold sparingly. Only for exercise names in progression and for section headers beyond H3.
- Say "is" instead of "serves as", "functions as", "represents".
- Be specific. "Your back volume is 12 sets/week, which is enough" not "Your back volume is adequate."

## Phase 1: Report (into workout_plan.md `## Report`)

Goals are fixed: hypertrophy + longevity. Never ask about goals.

Keep the report tight. The user is an established trainee who has been coached before. If the data shows continuity (same exercises, steady progression, no new red flags), shorten WHAT'S WORKING and WHAT NEEDS FIXING to 2-3 items each. Only surface findings that changed since the last block. The report should feel proportional to what's new.

### The verdict
2-3 sentences. What's the state of their training right now? Honest.

### What's working
Bullet points. Plain language. What they're doing well with specific exercises and numbers. 3-5 items max.

### What needs fixing
Bullet points. Prioritized by impact. Each item: what's wrong, why it matters for them, what to do. 3-5 items max. No technical justification beyond one sentence.

### Are you getting stronger?
For each major exercise with enough data:

`Exercise Name: Xkg × Y reps → Xkg × Y reps — getting stronger / stuck / going backwards`

If data is too limited to judge, say that in one sentence.

**Data sufficiency thresholds:**
- Progression trend: minimum 3 sessions with the same exercise over 2+ weeks. Below that, state "not enough data" for that exercise.
- Volume analysis: minimum 2 full training weeks. Below that, report what's visible but caveat the sample size in THE VERDICT.
- Single-session data: skip ARE YOU GETTING STRONGER entirely. State why.

### Missing from your tracking
List what the tracker doesn't capture that would help you coach better. One line each. (This draws from §13 internally but don't cite it.)

## Phase 2: Planning (into workout_plan.md `## Plan`)

If the user specified a session count in the `/coach` message (e.g., `/coach plan 3 sessions`), use it directly. Otherwise, ask in chat: **"How many sessions should I plan?"** — and wait for the answer before writing the file.

Generate that many strength workouts.

### Programming (internal)

**Split rotation:** The user runs a Push/Pull/Legs cycle. To determine the next sessions, look at the last completed workout's type and continue the rotation. Don't analyze the full history to rediscover this. If the last session was Pull, the next sessions are Legs → Push → Pull → Legs. If Push, next is Pull → Legs → Push → Pull. Fixed.

**Progression data:** The Step 4 summary already gives you weights and reps per exercise. Use that directly. Don't re-derive trends by walking through each exercise's history. Apply the double progression rule from §15: if the user hit the top of the rep range, bump weight. If not, same weight, push reps.

**Session duration:** 8-11 working exercises (excluding warmup) fits the 70-85 minute window. Count exercises, don't calculate minutes. At 7, add one. At 12, cut one.

Use Layer 1 analysis plus the training science reference. The reference contains the full rules; apply them:
- **Split selection** (§14): match split to session count. Keep existing split unless there's a problem.
- **Mesocycle structure** (§15): tell the user where they are in the block and what this week's targets are. No static plans.
- **Exercise pairing** (§16): straight sets for compounds, supersets for isolation/accessories when it saves time.
- **Exercise variation** (§17): the week's exercise selection must cover different regions of each major muscle. Anchor compounds where progression is live carry forward; variation plays out in isolation/accessory slots and across blocks.
- **Volume, frequency, overload, push-pull balance, lengthened position, tendon safety, HRV session placement, deload timing**: §1, §5, §6, §7, §8, §9, §11.
- Fix gaps from the report (underdeveloped muscles, missing patterns).
- Maintain exercises the user is already progressing on.
- No cardio in the plan.

**Core training:** Build strong, developed abs. Program 1-2 core exercises per session, aim for 3-4 sessions/week with core. Prefer weighted core (kneeling cable crunch, cable woodchop, captain's chair knee raise) alongside bodyweight (leg raises, dead bugs, hollow body holds). Vary patterns across sessions: flexion, anti-extension, rotation, isometric. Visibility is a body fat question, not a training question.

**Cable weight granularity:** Cable machines increment in 5kg steps: 5, 10, 15, 20, 25. Never suggest intermediate weights. Always round to the nearest available plate.

**Exercise ordering:** Compounds first, then isolation, then accessories.

**Equipment grouping:** Applies within the isolation/accessory block only. Batch cable work together, bench work together, etc. Never reorder compounds or move an isolation before a compound for equipment convenience.

**Priority notes:** In the Notes column, mark high-priority exercises "Priority" and droppable ones "Nice to have". Only when the distinction matters.

### Per-workout format in the file

For each workout, output the quick list immediately followed by the table for that same workout. Then move to the next workout. Do NOT batch all quick lists then all tables — that makes the file hard to use on the gym floor.

Correct order: Quick List WO1 → Table WO1 → Quick List WO2 → Table WO2 → etc.

**Quick list** — what the user reads on their phone. One line per set, plain markdown bullets. No code fences. Format:
- Bodyweight or single-rep: `Exercise Name : reps` (e.g., `Plank : 45s hold`)
- Weighted: every set separated by `///`:
  - Fixed: `Dumbbell Flat Bench Press: 52kgx10 /// 52kgx10 /// 52kgx10`
  - Range: `Cable Lat Pulldown: 65-70kgx8-10 /// 65-70kgx8-10 /// 65-70kgx8-10`
  - 4 sets = 4 entries. Always.
- Warmup exercises: same format, no special marking.

Example (markdown — no code fence around it in the actual file):

```
### Workout 1: UPPER PUSH + CORE

- Jumping Jacks : 50
- Band Pull-Apart : 15
- Dumbbell Flat Bench Press: 54kgx8-10 /// 54kgx8-10 /// 54kgx8-10 /// 54kgx8-10
- Shoulder Press Machine: 45kgx8-10 /// 45kgx8-10 /// 45kgx8-10
- Dumbbell Fly: 18kgx10 /// 18kgx10 /// 18kgx10
- Cable Lateral Raise: 15kgx10 /// 15kgx10 /// 15kgx10
- Cable Overhead Tricep Extension: 35kgx8-10 /// 35kgx8-10 /// 35kgx8-10
- Kneeling Cable Crunch: 20kgx15 /// 20kgx15 /// 20kgx15
- Dead Bug : 12 per side /// 12 per side
```

Canonical exercise names (title case from the database). No lowercase.

**Table** — reference for the same workout, single continuous table, core in the same table:

```
| # | Exercise | Sets × Reps | Notes |
| - | -------- | ----------- | ----- |
| 1 | Jumping Jacks | 1 × 50 | Warmup |
| 2 | Dumbbell Flat Bench Press | 4 × 8-10 | Start 54kg. Leave 1-2 reps in tank. |
...
| N | Dead Bug | 2 × 12/side | Anti-extension |
```

Rules for tables:
- **#**: sequential from 1
- **Exercise**: canonical names
- **Sets × Reps**: `3 × 8-10` or `1 × 50` or `1 × max hold`
- **Notes**: always specific. Include starting weight (from tracker or estimate), target ("Push for 10 reps before adding weight"), cue ("Full stretch at bottom"), purpose ("Warmup", "Shoulder health"). Never empty for working sets. Use "Leave 1-2 reps in the tank" / "All-out last set" instead of RIR/RPE numbers.
- 2-3 warmup exercises at the top
- Order: compounds → isolation → accessories

### Why this plan
One short paragraph at the end of the file — 3-4 sentences. What the overall block prioritizes and why these sessions are structured this way.

## Common Mistakes

| Failure mode | What goes wrong | Correct behavior |
|---|---|---|
| Double-counting synergist volume | Bench counted as 1 chest + 0.5 triceps, then overhead press also adds 0.5 front delt, and both get summed without deduplication | Track each compound's synergist contribution separately. Sum per muscle across all exercises. |
| Warmup sets counted as working volume | `Jumping Jacks 1×50` treated as a hard set | Warmup exercises and sets with `(warmup)` in Notes are excluded from hard-set counts. |
| Generic advice when data is thin | "You should probably add more back work" without numbers | State exactly what you can see ("2 sessions, 4 back sets") and what you can't conclude. |
| Progression call on insufficient data | "Bench press is stalling" from 2 data points | Need 3+ sessions over 2+ weeks. Below that: "not enough data to call a trend." |
| Inventing numbers not in the tracker | Estimating weights/reps the user didn't log | Only use data present. Empty field = unknown. |
| Ignoring sheet structure | Reading template sheets or non-`YYYY.MM` sheets | Only read sheets matching the regex. Ignore `Exercises Database` and any `New Month` / `How To Use` templates. |
| Impossible cable weights | Suggesting 12kg or 17kg | Cable increments in 5kg steps. Round to the nearest plate. |
| Scattering equipment | Cable exercises in positions 2, 5, 9 of the session | Batch by equipment within the isolation/accessory block. Never break compound order. |
| Neglecting core | Zero or one core exercise across a full planned week | 1-2 per session, 3-4 sessions/week. Vary patterns. |
| Running the same exercises every session | Weekly volume looks fine but regions of each muscle go chronically under-stimulated (§17) | The week's selection must cover different regions per target muscle. Use the `exercises-database.md` tags to pick the second variant. |
| Over-rotating variants every block | No single exercise repeats often enough to read a progression trend | Keep at least one anchor per muscle stable. Rotate 1-2 secondary variants per mesocycle, not the main lifts. |
| Static plan with no mesocycle context | Weights and reps with no indication of block position | Tell the user where they are in the mesocycle and what this week targets (§15). |
| Missing data from casing mismatch | Searching for "Leg Extension" misses rows logged as "Leg extension" | Compare case-insensitively. |
| Reading empty template rows | Dumping 900+ rows per sheet into context | Stop after 10 consecutive fully empty rows. |
| Breaking on None date | `if row[0] is None: break` stops at the first continuation row | Carry forward the last known date defensively. Only skip when BOTH date and exercise are None. |
| Writing the report or plan inline in chat | Conversation gets flooded; plan is hard to find later | All report + plan content goes into `./workout_plan.md`. Chat gets one verdict line + the file pointer. |
| Partial file writes | Streaming sections and forgetting to complete | Build the whole file in memory, then write once. |

## Rules

- Goals fixed. Never ask.
- No generic advice disconnected from their data.
- Don't soften findings.
- If data is too thin, say what you can and can't tell from it.
- One clarifying question max if the tracker is unreadable.
