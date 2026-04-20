---
name: workout-tracker-maintenance
description: >
  ONLY activate when the user's message starts with "/maintain". Runs end-of-month
  maintenance on Workout_Tracker.xlsx: restyles all sheets, trims empty rows/cols,
  reorders sheets (DB first, months newest → oldest), and verifies data integrity.
  Idempotent. Do NOT trigger on general spreadsheet questions, formatting requests,
  or anything that doesn't begin with the literal command "/maintain".
---

# Workout Tracker Maintenance

**Trigger**: Message starts with `/maintain`. No other messages.

Run this at the end of each month (or any time the sheet looks messy). It's idempotent — safe to run repeatedly.

## When NOT to Use

- General spreadsheet formatting questions
- Ad-hoc styling requests
- No `Workout_Tracker.xlsx` in the conversation or project directory

## What It Does

1. **Reapplies canonical styling** to every sheet (header row, data rows, section headers on Exercises Database, column widths, freeze pane, session separators on monthly sheets). Self-heals any manual formatting drift.
2. **Trims empty rows and columns**. Keeps a buffer so active logging still works:
   - Exercises Database: no buffer (static lookup).
   - Current-month sheet: 50 blank rows (room to log).
   - Past-month sheets: 2 blank rows.
   - Columns capped at 5 (DB) / 12 (monthly).
3. **Reorders sheets**: `Exercises Database` first, then monthly sheets newest → oldest.
4. **Verifies data integrity**: compares nonempty row counts before/after; aborts if any data was lost.
5. **Takes a safety backup** (`Workout Tracker.maintain-backup.xlsx`) before writing.

## How to Run

Ask the user to confirm the path to `Workout_Tracker.xlsx`, then:

```bash
python3 scripts/maintain.py "/path/to/Workout Tracker.xlsx"
```

For a preview without writing:

```bash
python3 scripts/maintain.py "/path/to/Workout Tracker.xlsx" --dry-run
```

The script lives at `scripts/maintain.py` inside this skill. Read it before running so you can explain what it will do if the user asks.

## After Running

Report:
- Final sheet order.
- Row counts per sheet (data rows + max_row).
- File size change, if notable.
- Any warnings surfaced by the verification step.

Do not edit the xlsx further unless the user asks — the script is the source of truth for style + structure.

## Canonical Style Reference

Kept here so the rules are visible and reviewable without reading the script.

### Row 1 header (all sheets)
- Fill `#BDC3C7`, bold black, size 10, centered, frozen.

### Data rows
- Fill `#F2F3F4`, size 10, centered (Notes column left-aligned on monthly sheets), no borders except session separators.

### Section headers (Exercises Database only)
- Muscle groups (`CHEST`, `BACK`, etc.): alternating navy `#2C3E50` (white text) and light gray `#D5D8DC` (black text), merged across all 5 columns.
- Subsections (`Horizontal Push (Compound)`, etc.): fill `#EAEDED`, italic bold black, merged across all 5 columns.

### Session separators (monthly sheets)
- Thin top border color `#BDC3C7` on the first row of each new date.

### Column widths

| Sheet | A | B | C | D | E | F | G | H | I | J | K | L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Exercises Database | 30 | 13 | 16 | 14 | 48 | — | — | — | — | — | — | — |
| Monthly | 12 | 5 | 28 | 5 | 6 | 6 | 9 | 24 | 13 | 14 | 13 | 9 |

## Automating Monthly

Three options, in order of hands-off-ness:

- **Claude Code Routines** (cloud cron). Visit https://claude.ai/code/routines or run `/schedule` and set a monthly trigger. The routine invokes `/maintain` on the 1st of each month. Runs even when your machine is off.
- **Claude Desktop Scheduled Tasks**. Same idea but runs locally.
- **Manual**. Invoke `/maintain` at end of month.

## Common Issues

| Symptom | Likely cause | Fix |
|---|---|---|
| "file not found" | Wrong path | Pass the full path including `Workout Tracker.xlsx` |
| "nonempty row count changed" | A delete went wrong | Restore from `Workout Tracker.maintain-backup.xlsx` and re-run with `--dry-run` to debug |
| Sheet appears unstyled after run | Opened in a viewer that ignores openpyxl styles | Open in Excel / Numbers / LibreOffice to verify |
| Current-month sheet has no blank rows to append | Buffer math off | Bump `CURRENT_MONTH_BUFFER` in the script |
