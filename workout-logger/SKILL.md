---
name: workout-logger
description: >
  Use when the user's message starts with "/log". Do NOT trigger on general
  fitness questions, training discussion, or workout logging that doesn't begin
  with the literal command "/log".
---

# Workout Logger

**Trigger**: Message starts with `/log`. No other messages.

## When NOT to Use

- General fitness questions
- Training discussion or advice
- Messages that mention logging but don't start with `/log`
- Requests to analyze or review past workouts (that's `/coach`)

## Setup

Read before processing:
- `../shared/exercises-database.md` — canonical exercise names and tags (shared with `/coach`)
- `references/aliases.md` — alias table, modifier handling, equipment defaults
- `references/parsing-rules.md` — parsing logic for all input formats
- `references/common-mistakes.md` — known parsing traps

The tracker lives at `./Workout Tracker.xlsx` in the current working directory. If it's not there, stop and say so in one line. Don't search the filesystem.

## Flow

1. Parse the message into row dicts — one per set — using the references above.
2. Write the rows as a JSON array to a temp file (e.g. `/tmp/workout_rows.json`).
3. Run `scripts/append_workout.py "Workout Tracker.xlsx" /tmp/workout_rows.json`. The script routes each row to its `YYYY.MM` sheet, creating the sheet with headers if missing.
4. Print the summary line: `N workouts, N exercises, N total sets, Wkg total volume`. If any session was marked as a deload, append ` (deload session)` to the line.

The tracker itself is the output. No markdown tables, no files presented, no narration.

## Session-level flags

**Deload.** If the word `deload` appears anywhere on the header line of a session (before the first exercise bullet), that session is a deload. Examples that all trigger it:
- `/log 22.04 deload`
- `/log deload 22.04`
- `/log 22.04 (deload)`

When set, put the exact string `Deload Workout` in the `notes` field of the **first row** of that session. Subsequent rows for that session are unchanged. If the user also wrote a parenthetical note on the first exercise, merge both: `"Deload Workout; warmup"`.

Multi-date `/log` messages: the `deload` keyword applies per session. The user must mark each date they want flagged.

## Row schema

Each row is a dict with these keys. `date` / `num` / `exercise` / `set` are required; the rest can be null.

```json
{
  "date": "2026-04-20",
  "num": 1,
  "exercise": "Dumbbell Flat Bench Press",
  "set": 1,
  "reps": 10,
  "kg": 52,
  "volume": 520,
  "notes": null,
  "distance_km": null,
  "duration_min": null,
  "pace": null,
  "avg_hr": null
}
```

Rules:
- `num` restarts at 1 for each new date. All sets of the same exercise share a `num`.
- `set` is 1, 2, 3 within an exercise.
- `volume` = `reps * kg`. Zero for bodyweight and cardio.
- The last four fields are cardio-only. Leave null for strength rows.
- The monthly sheets are always 12 columns. There is no "strength vs cardio" schema switch.
- Sort rows in the JSON by date ascending, then `num`, then `set`. The script does not re-sort.

## Rules

- No coaching. No suggestions. No opinions.
- One clarifying question max if input is genuinely unreadable.
- Never invent data.
- No narration. Don't show parsing steps, intermediate summaries, or thinking out loud. Go directly from input to script call to summary line.
