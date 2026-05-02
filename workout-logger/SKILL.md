---
name: workout-logger
description: >
  Appends a parsed workout to the requested person's tracker (e.g.
  ./Workout Tracker - Nihad.xlsx) with canonical styling applied to the new rows.
  Invoked by the `/log` slash command or when the user explicitly asks to log a
  workout. Do NOT trigger on general fitness questions, training discussion, or
  anything that isn't an explicit request to record a workout.
---

# Workout Logger

**Invocation**: The `/log` slash command delegates here. You can also be asked directly ("log this workout: …"). Do not trigger on anything else.

## Who is this for?

Two trackers live alongside each other in the workout directory:
- `Workout Tracker - Nihad.xlsx`
- `Workout Tracker - Fabian.xlsx`

Resolve which tracker this log is for BEFORE running the script:
- If the user names a person ("log Fabian's push day", "this is for Nihad"), use that tracker.
- If the user uses pronouns or context that clearly refer to one person ("my bf" / "boyfriend" → Fabian; "I" / "me" / "my" with no other person mentioned → Nihad, since Nihad is the account owner), use that tracker.
- Otherwise ask: **"Is this for Nihad or Fabian?"** before proceeding.

Pass the resolved path to `append_workout.py`. Bodyweight entries, deload flags, and all other session data route into whichever tracker file you picked — never split one session across both.

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

The tracker for the resolved person (`./Workout Tracker - <Person>.xlsx`) lives in the current working directory. If it's not there, stop and say so in one line. Don't search the filesystem.

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
3. Run `python3 scripts/append_workout.py "Workout Tracker - <Person>.xlsx" /tmp/workout_payload.json` (where `<Person>` is the resolved name, e.g. `Nihad` or `Fabian`). The script routes rows to the right `YYYY.MM` sheet, upserts bodyweight entries on the `Bodyweight` sheet (creating it if missing), and applies canonical styling to both.
4. **Verify the write succeeded.** Capture the script's stdout and exit code:
   - If the exit code is non-zero, print the exact stderr output and stop. Do not report success.
   - If the exit code is 0 but stdout does not contain the word `Appended`, print the exact stdout and stop with: "Unexpected script output — please check the tracker manually."
   - If stdout contains `Appended`, the write is confirmed. Proceed.
5. Print the summary line: `N workouts, N exercises, N total sets, Wkg total volume`. If any session was marked as a deload, append ` (deload session)`. If one or more weights were logged, append ` | morning weight: 78.4kg` (or comma-separate multiple dates). The summary comes from the script's `Appended …` stdout line — extract N rows and dates from it.

6. **Apple Health refresh prompt.** After printing the summary line, ALWAYS ask the user via `AskUserQuestion`:

   > Question: "Refresh Apple Health data?"
   > Options: `Refresh now`, `Skip`

   On `Refresh now`, resolve the export file in this priority order:

   1. `./Export - <Person>.zip` (Apple's native XML, per-person)
   2. `./Export.zip` (Apple's native XML, single-user fallback)
   3. `./health_export_*.txt` (HLExport text dump — globbed; **most recent by mtime wins**, never naming-pinned to a person, since the user drops one fresh file at a time)

   If none exists, print one line: `No Apple Health export found — skipping.` and finish.

   Dispatch by file extension:

   - `.zip` → `python3 Skills/shared/import_apple_health.py --zip <found_zip> --tracker "Workout Tracker - <Person>.xlsx"`
   - `.txt` → `python3 Skills/shared/import_hl_export.py --txt <found_txt> --tracker "Workout Tracker - <Person>.xlsx"`

   Both default to 6 months back (no `--since` needed). Capture stdout. Append the importer's `Health Metrics: …` and `Workout Sessions: …` summary lines (and any `Auto-cardio: …` / `Profile: …` lines) to the user-facing summary printed in step 5.

   **Source-mismatch guardrail.** Before dispatching, peek at the tracker's `Profile.source` value (the importer creates the Profile sheet on first run, but a user may have hand-edited it). If the file extension implies a different source than the tracker is configured for, stop and ask once via `AskUserQuestion` before importing:

   > "This tracker is configured for `<current_source>`, but only an `<other>` export was found. Switch this tracker to `<other_source>`?"
   > Options: `Switch and import`, `Skip import`

   On `Switch and import`, the importer will update `Profile.source` on its next write (HL bootstrap + XML bootstrap both honor existing values, so a manual `write_profile` from the logger isn't required — just dispatch the matching script and it writes the right defaults if the sheet was missing). On `Skip import`, finish without running the importer. Sparse-merge means switching mid-stream is safe: existing values aren't erased, and the new source only fills cells it can.

   On `Skip` to the original prompt: print nothing extra, finish.

   The prompt fires on every `/log` run by design — the user opted into this flow. A silent skip is not equivalent to "Skip"; always ask. Idempotent re-runs are fine — the importer's sparse-merge protects existing data.

The tracker itself is the output. No markdown tables, no files presented, no narration.

## Apple Health refresh

The logger never imports Apple Health on its own — it shells out to one of two importers based on the file extension found in the working directory:

- `Skills/shared/import_apple_health.py` for `Export*.zip` (Apple's native XML; full feature surface — VO2max, RHR, HRV, wrist temp, sleep stages, per-workout HR).
- `Skills/shared/import_hl_export.py` for `health_export_*.txt` (HLExport text dump; lighter feature surface — VO2max, HR Recovery, total sleep, resp rate, bodyweight, workout durations / distance / calories. No HRV, no wrist temp, no per-workout HR, no sleep stages.)

Both write into the same two tracker sheets:

- `Health Metrics` — daily aggregates. Cells the active source can't fill stay None; sparse-merge protects any older values from a previous source.
- `Workout Sessions` — one row per Apple `Workout`. HR columns are populated for XML, blank for HL.

Both also create / read a hidden-by-convention `Profile` sheet that pins the per-tracker `source` (`xml` | `hl_export`) and `auto_cardio` flag. The coach's `read_tracker.py` reads this to decide which sections of the report it can fill.

**File-naming conventions.**

- XML: each person drops their own export into the workout tracker folder, named `Export - <Person>.zip`. If only `Export.zip` exists (single-user setup), fall back to that.
- HL: drop the export from the HLExport iOS app as `health_export_<timestamp>.txt`. Don't rename — the resolver globs by pattern and picks the most recent by mtime, so dropping a fresh export and walking away is the intended flow. Different people each work with one file at a time; if both Nihad and Fabian want HL exports active simultaneously, swap one out before running the logger for the other.

**Idempotency.** Re-running with the same export is a no-op. Sparse-merge upserts protect existing values — incoming `None` never overwrites a populated cell, so a partial export (e.g. just last week) won't erase older history. Switching a tracker from XML to HL (or vice versa) mid-stream is safe: the new source only fills cells it can, and old XML-derived HRV / wrist temp etc. stay put.

**Auto-cardio.** When the importer ingests cardio workouts (Running, Hiking, Cycling, Swimming, HIIT) AND `Profile.auto_cardio` is True, those workouts also flow into the matching `YYYY.MM` monthly sheet as cardio rows tagged `auto-imported from Apple`. Manually-logged rows always win — the dedupe rule (date + exercise + duration ±1 min) skips Apple workouts that match an existing manual entry. Default: `auto_cardio = true` for XML trackers, `false` for HL trackers (flip via the Profile sheet once HL workout records prove reliable).

**Step 6 always asks.** No watchers, no cron, no auto-detection. The user picked this flow explicitly: ask every time, accept "Skip" cleanly. Never silently skip just because no export is in the folder.

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

When set, put the exact string `Deload Workout` in the `notes` field of any row of that session. The styler hoists the marker onto the session's `TOTAL` row Notes column alongside the other session-level metadata (Avg HR, Active Cal, Duration, etc.) — that's the canonical home. Don't merge it with per-exercise warmup comments; user notes (like "felt strong" on the warmup row) stay on their own row, and the deload marker rides on TOTAL. The warmup row's Notes stays free for the user.

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
