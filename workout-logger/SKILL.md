---
name: workout-logger
description: >
  ONLY activate when the user's message starts with "/log". Do NOT trigger on
  general fitness questions, training discussion, workout logging without the
  /log prefix, or anything that doesn't begin with the literal command "/log".
---

# Workout Logger

**Trigger**: Message starts with `/log`. No other messages.

## When NOT to Use

- General fitness questions
- Training discussion or advice
- Messages that mention logging but don't start with `/log`
- Requests to analyze or review past workouts (that's `/coach`)

## Setup

Read all references before processing:
- `references/exercises-database.md` — canonical exercise names and tags
- `references/aliases.md` — alias table, modifier handling, equipment defaults
- `references/parsing-rules.md` — parsing logic for all input formats
- `references/file-generation.md` — column schema and openpyxl template
- `references/common-mistakes.md` — known parsing traps

## Output

Three things, in order:

1. `Logging workout from YYYY-MM-DD`
2. Generate the `.xlsx` file and present it (see `references/file-generation.md`)
3. `X workouts, Y exercises, Z total sets, Wkg total volume`

No markdown table. The file is the output. Stop there.

## Rules

- No coaching. No suggestions. No opinions.
- One clarifying question max if input is genuinely unreadable.
- Never invent data.
- No narration. Do not show parsing steps, intermediate summaries, or thinking out loud. Go directly from input to file generation to summary line.
