---
name: workout-tracker-maintenance
description: >
  ONLY activate when the user's message starts with "/maintain". Runs
  end-of-month maintenance on a workout tracker (xlsx + per-person CSVs):
  restyles the monthly YYYY.MM sheets, trims empty rows/cols, reorders sheets,
  validates the per-person CSV store. Idempotent. Do NOT trigger on general
  spreadsheet questions, formatting requests, or anything that doesn't begin
  with the literal command "/maintain".
---

# Workout Tracker Maintenance

**Trigger**: Message starts with `/maintain`. No other messages.

Run this at the end of each month (or any time the sheet looks messy). It's idempotent — safe to run repeatedly.

## Who is this for?

Two trackers live in per-person folders:
- `Nihad/Workout Tracker - Nihad.xlsx` + `Nihad/data/*.csv`
- `Fabian/Workout Tracker - Fabian.xlsx` + `Fabian/data/*.csv`

Resolve which person(s) `/maintain` should run on:
- If the user names a person ("/maintain fabian"), run for that one.
- If the user says "both" or runs `/maintain` bare at end of month, offer to run on both back-to-back (one `python3 scripts/maintain.py --person <Name>` invocation per person).
- Otherwise ask: **"Is this for Nihad, Fabian, or both?"** before proceeding.

The script's safety backup (`Workout Tracker - <Person>.maintain-backup.xlsx`) lands inside the person's folder.

## When NOT to Use

- General spreadsheet formatting questions
- Ad-hoc styling requests
- No tracker in the conversation or project directory

## What It Does

1. **Reapplies canonical styling** to every monthly sheet (header row, data rows, column widths, freeze pane, session separators). Self-heals any manual formatting drift.
2. **Trims empty rows and columns** on monthly sheets:
   - Current-month sheet: 50 blank rows (room to log).
   - Past-month sheets: 2 blank rows.
   - Columns capped at 18.
3. **Reorders sheets**: monthly sheets newest → oldest. Warns if any non-monthly sheet survived the PR1 migration.
4. **Verifies data integrity**: compares nonempty row counts before/after; aborts if any data was lost.
5. **Validates per-person CSVs**: checks header schema match (against the active `Profile.source`), monotonic-DESC dates, and reports row counts.
6. **Takes a safety backup** (`Workout Tracker - <Person>.maintain-backup.xlsx`) before writing.

## How to Run

After resolving the person (see "Who is this for?" above):

```bash
python3 scripts/maintain.py --person <Person>
```

For a preview without writing:

```bash
python3 scripts/maintain.py --person <Person> --dry-run
```

When running on both, invoke the script twice — once per person — and report results per person.

For the historical meter-as-km swim fix sweep, add `--fix-distance-units` (with optional `--dry-run`).

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

### Column widths (monthly sheet, 18 cols)

| Col | A | B | C | D | E | F | G | H | I | J | K | L | M | N | O | P | Q | R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Width | 8 | 12 | 5 | 28 | 5 | 6 | 6 | 9 | 24 | 13 | 14 | 13 | 9 | 11 | 11 | 13 | 11 | 7 |

## Automating Monthly

Three options, in order of hands-off-ness:

- **Claude Code Routines** (cloud cron). Visit https://claude.ai/code/routines or run `/schedule` and set a monthly trigger. The routine invokes `/maintain` on the 1st of each month. Runs even when your machine is off.
- **Claude Desktop Scheduled Tasks**. Same idea but runs locally.
- **Manual**. Invoke `/maintain` at end of month.

## Common Issues

| Symptom | Likely cause | Fix |
|---|---|---|
| "tracker not found" | Wrong person name | Pass `--person Nihad` or `--person Fabian` |
| "nonempty row count changed" | A delete went wrong | Restore from `<Person>/Workout Tracker - <Person>.maintain-backup.xlsx` and re-run with `--dry-run` to debug |
| Sheet appears unstyled after run | Opened in a viewer that ignores openpyxl styles | Open in Excel / Numbers / LibreOffice to verify |
| Current-month sheet has no blank rows to append | Buffer math off | Bump `CURRENT_MONTH_BUFFER` in the script |
| "WARN: unexpected non-monthly sheets in xlsx" | A pre-PR1 dense sheet (Profile, Health Metrics, …) snuck back into the xlsx | Re-run the migration: `python3 Skills/shared/migrate_xlsx_to_csv.py --person <Person>` |
| "header mismatch" on a CSV | Profile.source flipped without a matching CSV rewrite | Re-run the matching importer with the current export, or hand-fix the header |
