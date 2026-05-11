---
name: workout-logger
description: >
  Appends a parsed workout to the requested person's tracker (per-month
  CSV under <Person>/data/monthly/) with canonical sort + computed
  cells applied on every write.
  Invoked by the `/log` slash command or when the user explicitly asks to log a
  workout. Do NOT trigger on general fitness questions, training discussion, or
  anything that isn't an explicit request to record a workout.
---

# Workout Logger

**Invocation**: The `/log` slash command delegates here. You can also be asked directly ("log this workout: …"). Do not trigger on anything else.

## Who is this for?

Two trackers live in per-person folders inside the workout directory:
- `Nihad/data/` (CSV store: monthly/ + dense + swimming/)
- `Fabian/data/` (same shape; no swimming/ for HL trackers)

Resolve which person this log is for BEFORE running the script:
- If the user names a person ("log Fabian's push day", "this is for Nihad"), use that name.
- If the user uses pronouns or context that clearly refer to one person ("my bf" / "boyfriend" → Fabian; "I" / "me" / "my" with no other person mentioned → Nihad, since Nihad is the account owner), use that name.
- Otherwise ask: **"Is this for Nihad or Fabian?"** before proceeding.

Pass the resolved name via `--person <Name>`. The path resolver
(`Skills/shared/person_paths.py`) finds the right `data/` folder.
Bodyweight entries, deload flags, and all other session data route into
that person's tracker — never split one session across both.

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

The tracker for the resolved person lives under
`<Person>/data/` (`monthly/YYYY.MM.csv` per month, plus the dense
CSVs at the data/ root). The `--person` flag resolves the paths
automatically; if the script exits non-zero, stop and say so in one
line. Don't search the filesystem.

## Flow

1. Parse the message into row dicts — one per set — using the references above. Collect the set of dates touched by this log. If the message contains an explicit bodyweight line (see parsing rules), also parse that into a bodyweight entry. If the user includes `CSS test` on the header line of a 400m + 200m TT pair (see parsing rules), parse the two times and assemble a `css_test` payload field.

   **Unknown-exercise gate (REQUIRED before building the payload).** For every distinct exercise name in the parsed rows, run `python3 Skills/shared/exercises_database.py lookup "<name>"`. The script consults both the canonical catalog and the alias table (case-insensitive). Three branches:

   - **Exit 0** with a canonical name printed → use that canonical name (which may differ from what the user typed by case, modifier handling, or alias). Replace the row's `exercise` value with the canonical form. Continue.
   - **Exit 1 (`UNKNOWN`)** AND `python3 Skills/shared/exercises_database.py fuzzy "<name>"` returns a top-1 hit with similarity ≥ 0.85 → high-confidence alias candidate. Show the user once via `AskUserQuestion`: "Looks like `<typed name>` is a typo of `<canonical>` (similarity X.XX). Add as alias?" Options: `Yes, add alias` / `No, this is a different exercise` / `Skip — log under the typed name`. On `Yes`, pipe `{"kind":"alias","user_input":"<typed>","canonical_name":"<canonical>"}` to `python3 Skills/shared/exercises_database.py propose --from-stdin`, then replace the row's exercise with the canonical form and continue. On `No`, fall through to the next branch (full research). On `Skip`, leave the row untouched (it will silently contribute zero volume in the coach; flag this in the run summary so the user can fix later).
   - **Exit 1 (`UNKNOWN`)** AND no high-confidence fuzzy match → dispatch a research sub-agent (`subagent_type: general-purpose`) with this prompt skeleton:

     > Identify the exercise "{typed_name}" for the workout tracker at `Skills/shared/exercises-database.md`. Use up to 3 web sources (manufacturer page, ExRx / StrengthLog, Wikipedia). Determine: (a) primary muscle in the catalog's vocabulary (CHEST / BACK / SHOULDERS / BICEPS / TRICEPS / QUADS / HAMSTRINGS / GLUTES / ADDUCTORS / CALVES / CORE / NECK / WARMUP / CARDIO / WELLNESS / FULL BODY), (b) which sub-section under that muscle fits (e.g. "Horizontal Push (Compound)", "Quad Isolation" — see the database for the canonical section names), (c) equipment tag in catalog vocabulary ([BB] / [DB] / [Cable] / [Machine] / [BW] / [Smith] / [LM] / [Band] / [Treadmill] / [Outdoor] / etc.), (d) synergist muscles (e.g. "+front delt, +triceps" for a chest press), (e) whether it's a lengthened-position movement (`◆`). Return a JSON object: `{"kind": "exercise", "name": "<canonical name>", "primary_muscle": "<MUSCLE>", "section": "<section>", "tags": ["[Equipment]", "+syn1", "+syn2", "◆"], "sources": ["url1", "url2"], "confidence": "high|medium|low"}`. If the exercise looks like a variant of an existing entry (e.g. a Technogym brand name for a generic machine), return `{"kind": "alias", "user_input": "<typed>", "canonical_name": "<existing canonical>", "notes_modifier": "<modifier if any>", "sources": [...], "confidence": "high|medium|low"}` instead.

     The sub-agent returns the proposal JSON. **Always surface it to the user via `AskUserQuestion` before writing** (regardless of confidence): show the proposed addition, list the sources, and ask `Add it` / `Edit first` / `Skip`. The user is the corruption guard.

     On `Add it`, pipe the JSON to `python3 Skills/shared/exercises_database.py propose --from-stdin`. The script atomically writes, re-parses, and rolls back if validation fails. On `Edit first`, ask the user for the corrected field and write the edited JSON. On `Skip`, leave the row untouched (will contribute zero volume — flag in summary).

   **Never block more than one prompt per unknown name**. If an exercise repeats across multiple sets, resolve once and reuse the answer for the whole session.
2. Build the payload JSON (wrapper form) and write it to a temp file (e.g. `/tmp/workout_payload.json`):
   ```json
   {
     "rows": [ ... parsed row dicts ... ],
     "bodyweight": [ {"date": "YYYY-MM-DD", "kg": 78.4, "notes": null}, ... ],
     "css_test": {"date": "YYYY-MM-DD", "t400_sec": 450, "t200_sec": 210}
   }
   ```
   Omit `bodyweight` entirely (or send `[]`) if the user didn't mention a weight. **Never prompt for it.** Omit `css_test` unless the user explicitly typed `CSS test` — never infer it. Per-lap swim data (Stroke / SWOLF / per-lap pace) cannot be entered manually; it comes from the Apple Health import only.
3. Run `python3 scripts/append_workout.py --person <Person> /tmp/workout_payload.json` (where `<Person>` is the resolved name, e.g. `Nihad` or `Fabian`). The script routes rows to the right `monthly/YYYY.MM.csv` under `<Person>/data/`, calls `canonicalize_monthly_csv` (sort + recompute Volume / Pace / SESSION + rebuild TOTAL rows), and mirrors any bodyweight entries into `<Person>/data/health_metrics.csv` (sparse-merge — never overwrites other metrics on that date).
4. **Verify the write succeeded.** Capture the script's stdout and exit code:
   - If the exit code is non-zero, print the exact stderr output and stop. Do not report success.
   - If the exit code is 0 but stdout does not contain the word `Appended`, print the exact stdout and stop with: "Unexpected script output — please check the tracker manually."
   - If stdout contains `Appended`, the write is confirmed. Proceed.
5. Print the summary line: `N workouts, N exercises, N total sets, Wkg total volume`. If any session was marked as a deload, append ` (deload session)`. If one or more weights were logged, append ` | morning weight: 78.4kg` (or comma-separate multiple dates). The summary comes from the script's `Appended …` stdout line — extract N rows and dates from it.

6. **Apple Health refresh prompt.** After printing the summary line, ALWAYS ask the user via `AskUserQuestion`:

   > Question: "Refresh Apple Health data?"
   > Options: `Refresh now`, `Skip`

   On `Refresh now`, the importer auto-resolves the export file from the
   workout-tracker root (one above the per-person folders):

   1. `./Export - <Person>.zip` (Apple's native XML, per-person)
   2. `./Export.zip` (Apple's native XML, single-user fallback)
   3. `./health_export_*.txt` (HLExport text dump — globbed; **most recent by mtime wins**)

   If none exists, the script prints `ERROR: no Apple Health export found …` and exits 1 — surface that one line to the user.

   Dispatch by file extension:

   - `.zip` → `python3 Skills/shared/import_apple_health.py --person <Person>`
   - `.txt` → `python3 Skills/shared/import_hl_export.py --person <Person>`

   Both default to 6 months back (no `--since` needed). Both **archive the source export to `<root>/.processed/` on success** — the per-person CSVs are the persistent record now; the archive keeps a forensic trail if a downstream bug damages the CSVs. Capture stdout and append the importer's `Health Metrics: …` and `Workout Sessions: …` summary lines (and any `Auto-cardio: …` / `Profile: …` / `Archived source export: …` lines) to the user-facing summary printed in step 5.

   **Source-mismatch guardrail.** Before dispatching, peek at the tracker's `Profile.source` value via `csv_store.read_profile(person)`. If the file extension implies a different source than the tracker is configured for, stop and ask once via `AskUserQuestion` before importing:

   > "This tracker is configured for `<current_source>`, but only an `<other>` export was found. Switch this tracker to `<other_source>`?"
   > Options: `Switch and import`, `Skip import`

   On `Switch and import`, the importer will update `Profile.source` on its next write. On `Skip import`, finish without running the importer. Sparse-merge means switching mid-stream is safe: existing values aren't erased, and the new source only fills cells it can.

   On `Skip` to the original prompt: print nothing extra, finish.

   The prompt fires on every `/log` run by design — the user opted into this flow. A silent skip is not equivalent to "Skip"; always ask. Idempotent re-runs are fine — the importer's sparse-merge protects existing data.

The tracker itself is the output. No markdown tables, no files presented, no narration.

## Apple Health refresh

The logger never imports Apple Health on its own — it shells out to one of two importers based on the file extension found in the working directory:

- `Skills/shared/import_apple_health.py` for `Export*.zip` (Apple's native XML; full feature surface — VO2max, RHR, HRV, wrist temp, sleep stages, per-workout HR).
- `Skills/shared/import_hl_export.py` for `health_export_*.txt` (HLExport text dump; lighter feature surface — VO2max, HR Recovery, total sleep, resp rate, bodyweight, workout durations / distance / calories. No HRV, no wrist temp, no per-workout HR, no sleep stages.)

Both write into the same per-person CSV store under `<Person>/data/`:

- `health_metrics.csv` — daily aggregates. Cells the active source can't fill stay None; sparse-merge protects any older values from a previous source.
- `workout_sessions.csv` — one row per Apple `Workout`. HR columns are populated for XML, blank for HL.
- (XML only) `swimming/swim_workouts.csv` + `swimming/swim_laps.csv` — per-swim aggregates (Pool Length, Strokes, SPL, Avg SWOLF, Stroke Mix, Location, Water Temp) and per-lap detail (Stroke, Duration, SWOLF). HL has no lap data, so HL trackers don't have a `swimming/` folder.

Both also create / read `<Person>/data/profile.csv`, a 2-column key/value file pinning the per-tracker `source` (`xml` | `hl_export`), `auto_cardio` flag, `birthday`, and the swim CSS keys (`swim_css_sec_per_100m`, `swim_css_set_at`, `swim_pool_length_default`). The coach's `read_tracker.py` reads this to decide which sections of the report it can fill.

**File-naming conventions.**

- XML: each person drops their own export into the workout tracker folder, named `Export - <Person>.zip`. If only `Export.zip` exists (single-user setup), fall back to that.
- HL: drop the export from the HLExport iOS app as `health_export_<timestamp>.txt`. Don't rename — the resolver globs by pattern and picks the most recent by mtime, so dropping a fresh export and walking away is the intended flow. Different people each work with one file at a time; if both Nihad and Fabian want HL exports active simultaneously, swap one out before running the logger for the other.

**Idempotency.** Re-running with the same export is a no-op. Sparse-merge upserts protect existing values — incoming `None` never overwrites a populated cell, so a partial export (e.g. just last week) won't erase older history. Switching a tracker from XML to HL (or vice versa) mid-stream is safe: the new source only fills cells it can, and old XML-derived HRV / wrist temp etc. stay put.

**Auto-cardio.** When the importer ingests cardio workouts (Running, Hiking, Cycling, Swimming, HIIT) AND `auto_cardio` in `profile.csv` is True, those workouts also flow into the matching `<Person>/data/monthly/YYYY.MM.csv` as cardio rows tagged `auto-imported from Apple`. Manually-logged rows always win — the dedupe rule (date + exercise + duration ±1 min) skips Apple workouts that match an existing manual entry. Default: `auto_cardio = true` on both XML and HL trackers (the old conservative HL opt-in was retired once HL workout records proved reliable). Flip to `false` per-tracker by editing `profile.csv` if a user prefers manual-only logging.

**Step 6 always asks.** No watchers, no cron, no auto-detection. The user picked this flow explicitly: ask every time, accept "Skip" cleanly. Never silently skip just because no export is in the folder.

## Bodyweight (opt-in)

Bodyweight is opt-in. Record it only when the user explicitly includes it in the `/log` message — see `references/parsing-rules.md` for the accepted formats. No automatic prompts, no probing for missing weights, no `AskUserQuestion`. If the user didn't mention a weight, don't record one.

The standing convention is **morning, empty stomach**. If the user writes something that implies a non-morning context (e.g. "after dinner"), include that in the entry's `notes` field (e.g. `"evening, not fasted"`).

### Bulk-seed (historical import)

To back-fill many historical weights at once, call `append_workout.py` with a payload of only bodyweight entries: `{"rows": [], "bodyweight": [{"date": "...", "kg": ..., "notes": null}, ...]}`. The logger forwards each entry into `<person>/data/health_metrics.csv` via the sparse-merge `upsert_health_metrics` — same dedupe-by-date semantics, but the bodyweight is now stored on the Health Metrics row (col B) alongside the rest of that day's metrics.

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
  "avg_hr": null,
  "laps": null
}
```

Rules:
- `num` restarts at 1 for each new date. All sets of the same exercise share a `num`.
- `set` is 1, 2, 3 within an exercise.
- Do NOT compute or include a `volume` field — `canonicalize_monthly_csv` recomputes Volume = reps × kg on every write and writes a literal sum on the TOTAL row. Skip the arithmetic.
- The cardio fields (`distance_km`, `duration_min`, `pace`, `avg_hr`) are cardio-only. Leave null for strength rows.
- `laps` is swim-specific: integer count of pool lengths (e.g. `22` for a `22 × 25 m = 550 m` swim). Leave null for non-swim rows. The Apple importer fills this from `HKWorkoutEventTypeLap` events; users can include it in `/log` via `<N> laps`, `<N> lengths`, or `<N> Bahnen`.
- The monthly CSVs have 18 columns: `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR | Active Cal | Total Cal | Elevation (m) | Elapsed | Laps`. SESSION is filled in by `canonicalize_monthly_csv` (per-month session number repeated on every row of the same date); leave it out of the row dict.
- Sort rows in the JSON by date ascending, then `num`, then `set`. The script does not re-sort.

## Rules

- No coaching. No suggestions. No opinions.
- One clarifying question max if input is genuinely unreadable.
- Never invent data.
- No narration. Don't show parsing steps, intermediate summaries, or thinking out loud. Go directly from input to script call to summary line.
