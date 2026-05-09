---
name: workout-tracker-maintenance
description: >
  ONLY activate when the user's message starts with "/maintain". Runs
  end-of-month maintenance on a workout tracker (per-person CSV store):
  canonicalizes every per-month workout CSV (sort + recompute Volume/
  Pace/SESSION + rebuild TOTAL rows), validates the per-person CSV
  store. Idempotent. Do NOT trigger on general spreadsheet questions,
  formatting requests, or anything that doesn't begin with the literal
  command "/maintain".
---

# Workout Tracker Maintenance

**Trigger**: Message starts with `/maintain`. No other messages.

Run this at the end of each month (or any time something looks off in the CSV store). It's idempotent — safe to run repeatedly.

## Who is this for?

Two trackers live in per-person folders:
- `Nihad/data/` (CSV store)
- `Fabian/data/` (CSV store)

Resolve which person(s) `/maintain` should run on:
- If the user names a person ("/maintain fabian"), run for that one.
- If the user says "both" or runs `/maintain` bare at end of month, offer to run on both back-to-back (one `python3 scripts/maintain.py --person <Name>` invocation per person).
- Otherwise ask: **"Is this for Nihad, Fabian, or both?"** before proceeding.

## When NOT to Use

- General spreadsheet formatting questions
- Ad-hoc styling requests
- No tracker in the conversation or project directory

## What It Does

1. **Canonicalizes every per-month CSV** (`<Person>/data/monthly/YYYY.MM.csv`): sort by (Date, #, Set), recompute Volume / Pace / SESSION, rebuild TOTAL rows, hoist deload markers. Self-heals any manual edits.
2. **Validates the per-person CSV store**: checks header schema match (against the active `Profile.source`) and monotonic date order on `health_metrics.csv` / `workout_sessions.csv` / `profile.csv` and every `monthly/YYYY.MM.csv`. When the optional `swimming/` folder exists (XML trackers with per-lap swim data), also validates `swim_workouts.csv` (DESC) and `swim_laps.csv` (ASC). Reports row counts.
3. **Optional `--fix-distance-units` sweep**: auto-fixes legacy meter-as-km swim distance bug across all per-month CSVs + `workout_sessions.csv` + `swim_workouts.csv`. Idempotent.

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
- Per-month CSV canonicalize summary (rows before → after).
- Per-CSV row counts and any header / order warnings from the validator.
- File size change, if notable.
- Any warnings surfaced by the verification step.

Do not edit the CSVs further unless the user asks — the canonicalizer is the source of truth for sort order + computed cells (Volume, Pace, SESSION, TOTAL rows).

## Canonical Layout Reference

Kept here so the rules are visible without reading the script.

### Per-month CSV (`<Person>/data/monthly/YYYY.MM.csv`)
- Header row 1, then ASC data rows by (Date, #, Set), TOTAL rows interleaved at strength-session boundaries.
- 18 columns: `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR | Active Cal | Total Cal | Elevation (m) | Elapsed | Laps`.
- `SESSION` is a per-month counter (1..N) repeated on every row of the same date (including TOTAL).
- `Volume` is `reps × kg` written as a literal number — recomputed on every canonicalize pass.
- `Pace (min/km)` is `duration / distance` formatted MM:SS, blanked outside [0.5, 60] min/km.
- `TOTAL` row (Exercise = "TOTAL") at every strength session boundary; carries the volume sum + Apple-watch session metadata (Duration, Avg HR, Active Cal, Total Cal, Elevation, Elapsed) + the Deload Workout marker on Notes when present.

### Dense CSVs (`<Person>/data/`)
- `health_metrics.csv` — DESC by Date.
- `workout_sessions.csv` — DESC by (Date, Start).
- `profile.csv` — `key,value` 2-column.
- `swimming/swim_workouts.csv` — DESC by (Date, Start). XML only.
- `swimming/swim_laps.csv` — ASC by (Date, Lap #). XML only.

## Automating Monthly

Three options, in order of hands-off-ness:

- **Claude Code Routines** (cloud cron). Visit https://claude.ai/code/routines or run `/schedule` and set a monthly trigger. The routine invokes `/maintain` on the 1st of each month. Runs even when your machine is off.
- **Claude Desktop Scheduled Tasks**. Same idea but runs locally.
- **Manual**. Invoke `/maintain` at end of month.

## Common Issues

| Symptom | Likely cause | Fix |
|---|---|---|
| "no monthly CSV directory" | Person folder was never set up, or was moved | Restore from iCloud version history; check `<Person>/data/monthly/` exists |
| "header mismatch" on a CSV | Profile.source flipped without a matching CSV rewrite, or hand-edit broke the schema | Re-run the matching importer with the current export, or hand-fix the header |
| "WARN dates not strictly ASC/DESC" | Hand-edit moved a row out of order | Re-run `/maintain` (canonicalize re-sorts every monthly CSV) |
| Computed cells look stale (Volume, Pace) | Hand-edit changed reps/kg/distance/duration without re-canonicalizing | Re-run `/maintain` — canonicalize recomputes on every pass |
