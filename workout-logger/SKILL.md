---
name: workout-logger
description: >
  Appends a parsed workout to ./Workout Tracker.xlsx with canonical styling
  applied to the new rows. Invoked by the `/log` slash command or when the
  user explicitly asks to log a workout. Do NOT trigger on general fitness
  questions, training discussion, or anything that isn't an explicit request
  to record a workout.
---

# Workout Logger

**Invocation**: The `/log` slash command delegates here. You can also be asked directly ("log this workout: …"). Do not trigger on anything else.

## When NOT to Use

- General fitness questions
- Training discussion or advice
- Requests to analyze or review past workouts (that's the `workout-coach` skill, invoked by `/coach`)

## Setup

Read before processing:
- `../shared/exercises-database.md` — canonical exercise names and tags (shared with `/coach`)
- `references/aliases.md` — alias table, modifier handling, equipment defaults
- `references/parsing-rules.md` — parsing logic for all input formats
- `references/common-mistakes.md` — known parsing traps

The tracker lives at `./Workout Tracker.xlsx` in the current working directory. If it's not there, stop and say so in one line. Don't search the filesystem.

## Flow

1. Parse the message into row dicts — one per set — using the references above. Collect the set of dates touched by this log. If the message contains an explicit bodyweight line (see parsing rules), also parse that into a bodyweight entry.
2. Build the payload JSON (wrapper form) and write it to a temp file (e.g. `/tmp/workout_payload.json`):
   ```json
   {
     "rows": [ ... parsed row dicts ... ],
     "bodyweight": [ {"date": "YYYY-MM-DD", "kg": 78.4, "notes": null}, ... ]
   }
   ```
   Omit `bodyweight` entirely (or send `[]`) if the user didn't mention a weight. **Never prompt for it.**
3. Run `python3 scripts/append_workout.py "Workout Tracker.xlsx" /tmp/workout_payload.json`. The script routes rows to the right `YYYY.MM` sheet, upserts bodyweight entries on the `Bodyweight` sheet (creating it if missing), and applies canonical styling to both — new rows land already styled.
4. Print the summary line: `N workouts, N exercises, N total sets, Wkg total volume`. If any session was marked as a deload, append ` (deload session)`. If one or more weights were logged, append ` | morning weight: 78.4kg` (or comma-separate multiple dates).

The tracker itself is the output. No markdown tables, no files presented, no narration.

## Bodyweight (opt-in)

Bodyweight is opt-in. Record it only when the user explicitly includes it in the `/log` message — see `references/parsing-rules.md` for the accepted formats. No automatic prompts, no probing for missing weights, no `AskUserQuestion`. If the user didn't mention a weight, don't record one.

The standing convention is **morning, empty stomach**. If the user writes something that implies a non-morning context (e.g. "after dinner"), include that in the entry's `notes` field (e.g. `"evening, not fasted"`).

### Bulk-seed (historical import)

To back-fill many historical weights at once, call `append_workout.py` with a payload of only bodyweight entries: `{"rows": [], "bodyweight": [{"date": "...", "kg": ..., "notes": null}, ...]}`. `upsert_bodyweight` dedupes by date and re-sorts newest-first.

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
- Do NOT compute or include a `volume` field — the sheet fills Volume via the formula `=reps*kg` and writes a SESSION total via `=SUM(...)` automatically. Skip the arithmetic.
- The last four fields are cardio-only. Leave null for strength rows.
- The monthly sheets have 13 columns: `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR`. SESSION is filled in by the styler (per-month session number, merged per date); leave it out of the row dict.
- Sort rows in the JSON by date ascending, then `num`, then `set`. The script does not re-sort.

## Rules

- No coaching. No suggestions. No opinions.
- One clarifying question max if input is genuinely unreadable.
- Never invent data.
- No narration. Don't show parsing steps, intermediate summaries, or thinking out loud. Go directly from input to script call to summary line.
