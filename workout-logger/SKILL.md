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
- `<Person>/data/` (CSV store: monthly/ + dense + swimming/)
- `<OtherPerson>/data/` (same shape)

Both are Health Export Kit–backed — there is one importer and one source.
Neither tracker has a per-lap swim store; see "Apple Health refresh" below.

Resolve which person this log is for BEFORE running the script:
- If the user names a person or tracker, use that name.
- If the user uses pronouns or context that clearly refer to one tracker, use that tracker.
- Otherwise ask which tracker/person this is for before proceeding.

Pass the resolved name via `--person <Name>`. The path resolver
(`Skills/shared/person_paths.py`) finds the right `data/` folder.
Bodyweight entries, deload flags, and all other session data route into
that person's tracker — never split one session across both.

## When NOT to Use

- General fitness questions
- Training discussion or advice
- Requests to analyze or review past workouts (that's the `workout-coach` skill, invoked by `/coach`)

## Setup

Use [parsing rules](references/parsing-rules.md) to interpret input and [common mistakes](references/common-mistakes.md) for tricky formats. The batch resolver reads the exercise catalog and alias table and returns the matching names and relevant alias notes. Open the catalog for a requested catalog review or edit.

The tracker for the resolved person lives under
`<Person>/data/` (`monthly/YYYY.MM.csv` per month, plus the dense
CSVs at the data/ root). The `--person` flag resolves the paths
automatically; if the script exits non-zero, stop and say so in one
line. Don't search the filesystem.

## Flow

1. Parse the message into row dicts — one per set — using the references above. Collect the set of dates touched by this log. If the message contains an explicit bodyweight line (see parsing rules), also parse that into a bodyweight entry. If the user includes `CSS test` on the header line of a 400m + 200m TT pair (see parsing rules), parse the two times and assemble a `css_test` payload field. If the message contains an explicit sleep line (see parsing rules), parse that into a `sleep` entry keyed to the session's date.

   **Resolve exercise names before building the payload.** When there are exercise rows, send their names as a JSON array on stdin to `python3 Skills/shared/exercises_database.py resolve-batch`. It returns one result per distinct name in input order, using case-insensitive catalog and alias matches. If the command fails, stop and report the error. Check the results against the context of the matching rows.

   - **`status: "known"`** with a canonical name → use that canonical name after checking any `alias_note` conditions against the row's actual context. Ask about a material ambiguity or keep the typed name unresolved. Explicit equipment and movement variants take precedence over defaults.
   - **`status: "unknown"`** AND its `candidate` has similarity ≥ 0.85 → high-confidence alias candidate. Show the user once via `AskUserQuestion`: "Looks like `<typed name>` is a typo of `<canonical>` (similarity X.XX). Add as alias?" Options: `Yes, add alias` / `No, this is a different exercise` / `Skip — log under the typed name`. **This prompt overrides auto-mode/default-mode assumptions; the user is the catalog-corruption guard, even for obvious plural/singular typos. Never write an alias without explicit approval.** On `Yes`, pipe `{"kind":"alias","user_input":"<typed>","canonical_name":"<canonical>"}` to `python3 Skills/shared/exercises_database.py propose --from-stdin`, then replace the row's exercise with the canonical form and continue. On `No`, leave the typed name unchanged unless the user explicitly requests identification or a catalog addition, in which case use the research flow below. On `Skip`, leave the row untouched (it will silently contribute zero volume in the coach; flag this in the run summary so the user can fix later).
   - **`status: "unknown"`** AND no high-confidence candidate → leave the typed name unchanged and flag it in the summary. Research it only if the user explicitly requests identification or a catalog addition. If requested, research using this prompt skeleton:

     > Identify the exercise "{typed_name}" for the workout tracker at `Skills/shared/exercises-database.md`. Use up to 3 web sources (manufacturer page, ExRx / StrengthLog, Wikipedia). Determine: (a) primary muscle in the catalog's vocabulary (CHEST / BACK / SHOULDERS / BICEPS / TRICEPS / QUADS / HAMSTRINGS / GLUTES / ADDUCTORS / CALVES / CORE / NECK / WARMUP / CARDIO / WELLNESS / FULL BODY), (b) which sub-section under that muscle fits (e.g. "Horizontal Push (Compound)", "Quad Isolation" — see the database for the canonical section names), (c) equipment tag in catalog vocabulary ([BB] / [DB] / [Cable] / [Machine] / [BW] / [Smith] / [LM] / [Band] / [Treadmill] / [Outdoor] / etc.), (d) synergist muscles (e.g. "+front delt, +triceps" for a chest press), (e) whether it's a lengthened-position movement (`◆`). Return a JSON object: `{"kind": "exercise", "name": "<canonical name>", "primary_muscle": "<MUSCLE>", "section": "<section>", "tags": ["[Equipment]", "+syn1", "+syn2", "◆"], "sources": ["url1", "url2"], "confidence": "high|medium|low"}`. If the exercise looks like a variant of an existing entry (e.g. a Technogym brand name for a generic machine), return `{"kind": "alias", "user_input": "<typed>", "canonical_name": "<existing canonical>", "notes_modifier": "<modifier if any>", "sources": [...], "confidence": "high|medium|low"}` instead.

     The research produces a proposal JSON. **Always surface it to the user via `AskUserQuestion` before writing** (regardless of confidence): show the proposed addition, list the sources, and ask `Add it` / `Edit first` / `Skip`. The user is the corruption guard.

     On `Add it`, pipe the JSON to `python3 Skills/shared/exercises_database.py propose --from-stdin`. The script atomically writes, re-parses, and rolls back if validation fails. On `Edit first`, ask for the corrected field and obtain explicit approval of the revised proposal before writing it. On `Skip`, leave the row untouched (will contribute zero volume — flag in summary).

   Resolve each repeated typed name once and reuse the decision for every matching row. Batch independent confirmations where the interface allows. A declined fuzzy alias is not approval of a different researched proposal: if the user requests research, ask separately for approval of the resulting proposal. Never add any alias or exercise without explicit approval of that addition.
2. Build the payload JSON (wrapper form) and write it to a unique private temporary file:
   ```json
   {
     "rows": [ ... parsed row dicts ... ],
     "bodyweight": [ {"date": "YYYY-MM-DD", "kg": 78.4, "notes": null}, ... ],
     "sleep": [ {"date": "YYYY-MM-DD", "total_h": 7.5, "deep_h": 1.2, "rem_h": 1.3,
                 "core_h": null, "unspecified_h": null, "awake_h": null,
                 "time_in_bed_h": 8.4, "efficiency_pct": null, "notes": null}, ... ],
     "css_test": {"date": "YYYY-MM-DD", "t400_sec": 450, "t200_sec": 210}
   }
   ```
   Omit `bodyweight` entirely (or send `[]`) if the user didn't mention a weight. **Never prompt for it.** Omit `sleep` entirely if the user didn't include a sleep line — **never prompt for sleep**. Omit `css_test` unless the user explicitly typed `CSS test` — never infer it. Per-lap swim data (Stroke / SWOLF / per-lap pace) cannot be entered manually, and no import supplies it either — the export carries only a lap count, not per-lap detail, so `swimming/*.laps.csv` is never written and `Avg SWOLF` / `Stroke Mix` stay blank. Per-night segment metadata also can't be entered manually: `first_segment_start` / `last_segment_end` / `n_segments` come from the importer only, and stay blank on manually-entered nights.
3. Run `python3 Skills/workout-logger/scripts/append_workout.py --person "<Person>" /path/to/private-payload.json`. The script routes rows to the right `monthly/YYYY.MM.csv` under `<Person>/data/`, calls `canonicalize_monthly_csv` (sort + recompute Volume / Pace / SESSION + rebuild TOTAL rows), mirrors any bodyweight entries into `<Person>/data/health_metrics.csv` (sparse-merge — never overwrites other metrics on that date), dual-writes any sleep entries into both `<Person>/data/sleep/YYYY.MM.nights.csv` (rich per-night detail) and `<Person>/data/health_metrics.csv` (headline Total/Deep/REM/Time in Bed for the recovery score). Sleep Efficiency is auto-derived inside the upsert when both Total and Time in Bed are present.
4. **Verify the write succeeded.** Capture the script's stdout and exit code:
   - If the exit code is non-zero, report the full output and stop. Exit 2 means unresolved set conflicts; other rows may already have been saved and committed.
   - If workout `rows` were present and the exit code is 0 but stdout does not contain the word `Appended`, print the exact stdout and stop with: "Unexpected script output — please check the tracker manually."
   - If no workout `rows` were present, a successful `Bodyweight:`, `Sleep Nights:`, `Nutrition Phases:`, or `CSS:` line confirms the write.
   - If stdout contains `Appended`, report the actual added, duplicate, replaced and conflict counts. Zero added rows may be an idempotent replay; do not claim they were newly logged. To correct an exact, unambiguous manual set, review it and use `--replace-conflicts`.
5. Before Apple Health refresh, report the `Appended` lines and any successful `Bodyweight:`, `Sleep Nights:`, `Nutrition Phases:`, or CSS status lines from stdout. These are the authoritative write results. Do not infer workout, exercise, set or volume totals from the payload: duplicate or conflicting rows may not have been added, and the append output does not provide those totals. Flag any names left unknown as described above. Use the same reporting in test runs.

6. **Apple Health refresh (automatic — no prompts at all).** After the summary, run `python3 Skills/shared/import_health_export_kit.py --person <Person>` unconditionally. See **Apple Health refresh** below for the source and store contract. No watchers or scheduled job are involved.

   Capture stdout and append the importer's `Health Metrics:`, `Sleep Nights:`, `Swim Workouts:`, `Workout Sessions:`, and any `Auto-cardio:`, `Strength clustering warnings:`, `Profile:`, `Archived source export:`, or `Committed <Person> data:` lines to the user-facing summary. Relay manual-wins warnings, skipped-negligible-swim lines, and nearby-swim notes. If no export exists, surface its one-line `ERROR: Health Export Kit file not found: health-export-json-*.json` and finish. A missing export means no fresh file was supplied.

The tracker itself is the output. No markdown tables, no files presented, no narration.

## Apple Health refresh

The logger never imports Apple Health on its own — it shells out to
`Skills/shared/import_health_export_kit.py`, which is **the only importer**.
It takes a single `health-export-json-*.json` file — no archive, no member
selection, no CSV fallback — and covers most of the tracker surface: VO2max,
RHR, walking HR, breathing disturbances, exercise minutes, steps, active /
basal energy, sleep stages, per-workout HR, and per-workout swim aggregates
(partial — see below). The native Apple XML importer and the older zip-based
Health Auto Export importer are both retired and removed.

It writes into the per-person CSV store under `<Person>/data/`:

- `health_metrics.csv` — 22 columns of daily aggregates, including the headline sleep fields (Sleep Total / Deep / REM / Time in Bed) and, appended immediately before `Notes`, `Steps` / `Active Energy (kcal)` / `Basal Energy (kcal)`. Cells the export can't fill stay None; sparse-merge protects existing values.
- `workout_sessions.csv` — one row per Apple `Workout`, HR columns populated.
- `swimming/YYYY.MM.workouts.csv` — per-swim rows: distance, duration, average HR, active energy, and a lap count when the export logged lap events. Pool Length, Strokes, SPL, Location and Water Temp have no source in this format and are left unset — sparse-merge preserves whatever the store already has rather than guessing. **No `swimming/YYYY.MM.laps.csv` is written.** The export carries only a lap count, not per-lap detail, so `Avg SWOLF` / `Stroke Mix` stay blank on new rows. Any existing `laps.csv` is frozen XML-era history.
- `sleep/YYYY.MM.nights.csv` — per-night sleep architecture: all stages the export exposes (Total, Core, Deep, REM, Unspecified, Awake) plus Time in Bed, Sleep Efficiency (derived), and First/Last Segment clock times (bedtime / wake-up schedule). `N Segments` is now populated — the count of sleep-stage entries recorded across the night's session(s); the retired importer always left it blank.

It also creates / reads `<Person>/data/profile.csv`, a 2-column key/value file pinning the per-tracker `source` (`health_export_kit` is what this importer writes; older source names were removed with the importers that wrote them), `auto_cardio` flag, `birthday`, and the swim CSS keys (`swim_css_sec_per_100m`, `swim_css_set_at`, `swim_pool_length_default`). The coach's `read_tracker.py` reads this to decide which assessment sections it can populate.

**What the import cannot see.** Apple's 1-10 per-workout effort score is gone permanently — `metadata` is empty on every JSON workout — so there is no RIR / RPE intake from the import path at all. Treat that as a permanent property of the source, not a provisional gap waiting on a better export. Per-lap swim detail and SWOLF are permanently out of reach for the same reason. Daily HRV SDNN and Wrist Temp are also never written by this importer (a change from the retired zip importer, which wrote both): the export's only HRV signal is a two-to-four-reading sleep-window average with roughly four times the variance of the historical all-day series, and mixing the two would corrupt the recovery score's rolling baseline.

**File naming.** Drop the app-generated `health-export-json-*.json` file into the workout tracker folder. When multiple matching files exist, pass the intended file explicitly with `--export`.

**Import conflicts.** Before any import write or archive, the importer checks populated health, sleep, swim, and workout-session cells that would change. It stops on conflicts and leaves the export in place. Review counts and all old/new values with `--dry-run`; use `--overwrite-existing` only when the replacements are intended. The store does not record field-level provenance, so a conflict does not show which value is newer. Empty fields can still be filled. Replaying equivalent values is conflict-free, including numeric formatting differences. A change to a populated sleep efficiency is reported even when recalculated from other fields, because it may be a manual override.

**The consumed export is archived.** After successful writes the importer copies and verifies the source under `<root>/archive/health-exports/YYYY-MM/`, then removes the incoming copy. `--keep-export` leaves it in place. Collisions never overwrite a different export. Data history is separate: each person's `data/` directory is its own git repository (`shared/data_git.py`), and both `append_workout.py` and the importer commit automatically after every confirmed write — one commit per operation, message `log: <N> rows, <dates>` or `import: <export file name>`.

**Auto-cardio.** When the importer ingests cardio workouts (Running, Hiking, Cycling, Swimming, HIIT) AND `auto_cardio` in `profile.csv` is True, those workouts also flow into the matching `<Person>/data/monthly/YYYY.MM.csv` as cardio rows carrying an `apple` / `gymkit:<Device>` value in the typed `Source` column. Manually-logged rows always win — the dedupe rule (date + exercise + duration ±1 min) skips Apple workouts that match an existing manual entry. Default: `auto_cardio = true`. Flip to `false` per-tracker by editing `profile.csv` if a user prefers manual-only logging.

For an explicit manual import, supported flags are `--person`, `--export` (path or glob), `--since`, `--until`, `--allow-past-months`, `--dry-run`, `--keep-export`, and `--overwrite-existing`. The default resolver accepts a single matching export; multiple matches require an explicit path. `/log` passes only `--person` and reports a conflict without overriding it.

## Bodyweight (opt-in)

Bodyweight is opt-in. Record it only when the user explicitly includes it in the `/log` message — see `references/parsing-rules.md` for the accepted formats. No automatic prompts, no probing for missing weights, no `AskUserQuestion`. If the user didn't mention a weight, don't record one.

The standing convention is **morning, empty stomach**. If the user writes something that implies a non-morning context (e.g. "after dinner"), include that in the entry's `notes` field (e.g. `"evening, not fasted"`).

### Bulk-seed (historical import)

To back-fill many historical weights at once, call `append_workout.py` with a payload of only bodyweight entries: `{"rows": [], "bodyweight": [{"date": "...", "kg": ..., "notes": null}, ...]}`. The logger forwards each entry into `<person>/data/health_metrics.csv` via the sparse-merge `upsert_health_metrics` — same dedupe-by-date semantics, but the bodyweight is now stored on the Health Metrics row (col B) alongside the rest of that day's metrics.

## Sleep (opt-in)

Sleep is opt-in. Record it only when the user explicitly includes a sleep line in the `/log` message — see `references/parsing-rules.md` for the accepted formats. **No automatic prompts, no probing for missing sleep, no `AskUserQuestion`.** If the user didn't mention sleep, don't record it.

Sleep entries are dual-written by `append_workout.py`:

- **Rich detail** → `<person>/data/sleep/YYYY.MM.nights.csv` via the sparse-merge `upsert_sleep_nights`. Captures all 6 stages Apple exposes (Total, Core, Deep, REM, Unspecified, Awake) plus Time in Bed, derived Sleep Efficiency, and first/last segment clock times. Manual entries leave the segment-metadata columns blank — only the importer populates those, including `N Segments`.
- **Headline mirror** → `<person>/data/health_metrics.csv`, columns Sleep Total / Sleep Deep / Sleep REM / Time in Bed. Sparse-merge protects every other metric on the same date. This is the path the coach's `recovery_score` already reads, so a manual sleep entry flows into the recovery score on the next `/coach` run.

If the user supplies only partial sleep info (e.g. just `sleep 7h30`), sparse-merge keeps the existing Apple-imported deep/REM/in-bed values on that date untouched and only updates the field(s) the user provided. A subsequent Apple import that would change the manually entered total reports a conflict and stops before writing unless explicitly overridden. Fields absent from the import remain unchanged.

Sleep Efficiency is auto-derived inside the upsert when both `total_h` and `time_in_bed_h` are present and `efficiency_pct` wasn't supplied as a manual override.

### Bulk-seed (historical sleep import)

To back-fill many historical sleep nights at once, call `append_workout.py` with a payload of only sleep entries: `{"rows": [], "bodyweight": [], "sleep": [{"date": "...", "total_h": ..., ...}, ...]}`. The logger routes each entry to the right `sleep/YYYY.MM.nights.csv` and mirrors the headline fields into `health_metrics.csv`. Same dedupe-by-date semantics as bodyweight.

The importer populates the `sleep/` folder when sleep-stage data exists. Manual sleep entries still dual-write there on demand, and the coach's stage-aware assessment sections gate on capabilities plus data presence so the user-facing output stays coherent.

## Nutrition phase (opt-in)

Nutrition phases (`bulk` / `cut` / `maintain` / `recomp`) are opt-in. The user signals one via a top-level line in the `/log` message:

- **`bulking start [date] [target X kcal] [protein X g/kg] [rate X %/wk or kg/wk] [stop: ...]`** opens a phase. The date defaults to today. Record only agreed targets. `stop:` stores the person's review criteria as text.
- **`bulking end [date]`** — closes the open bulk phase. `date` defaults to today.
- **`bulking update [field=value ...]`** — updates the open bulk phase's targets / notes. Same keys as start (target, protein, rate, stop, notes).
- The same three commands exist for `cutting`, `maintaining` and `recomp`. Keep gain rates positive and loss rates negative.

**No automatic prompts, no probing, no `AskUserQuestion`.** Absent ≡ didn't happen.

Phases are stored in `<Person>/data/nutrition_phases.csv`, one row per start date. The weekly coach reviews the latest open phase. When switching phases, end the previous phase and record the new start.

Payload shape — add a `nutrition_phase` key alongside `rows` / `bodyweight` / `sleep`:

```json
{
  "rows": [],
  "nutrition_phase": [
    {
      "start_date": "2026-05-11",
      "end_date": null,
      "phase_type": "bulk",
      "target_kcal_delta": 300,
      "target_protein_g_per_kg": 1.8,
      "target_rate_percent_per_week": 0.25,
      "reference_weight_kg": 75,
      "stop_conditions": "Review if weight is persistently above the agreed rate",
      "notes": "First gain phase after maintenance"
    }
  ]
}
```

The logger sparse-merges phase entries by `Start Date`. Existing `target_rate_kg_per_wk` targets are accepted. A supplied percentage takes precedence. The optional reference weight fixes conversions between percent and kilograms. The weekly coach reviews comparable within-phase weigh-ins and can defer a change when the trend is unresolved. Intake and protein targets are recorded separately from measurements.

### Bulk-seed (historical nutrition phases)

To back-fill historical phases (e.g. tracking prior bulks/cuts retroactively), call `append_workout.py` with a payload of only phase entries: `{"rows": [], "nutrition_phase": [{"start_date": "2025-01-15", "end_date": "2025-03-10", "phase_type": "cut", "target_rate_kg_per_wk": -0.5, "notes": "post-holidays cut"}, ...]}`. Multiple phases can be seeded in one call; the upsert dedupes on `Start Date`.

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
  "gym": null,
  "machine": null,
  "load_basis": null,
  "distance_km": null,
  "duration_min": null,
  "pace": null,
  "avg_hr": null
}
```

Rules:
- `num` restarts at 1 for each new date. All sets of the same exercise share a `num`.
- `set` is 1, 2, 3 within an exercise.
- Do NOT compute or include a `volume` field. The canonicalizer computes volume for known total loads; a plates-only load leaves exercise and session total volume blank because the total is unknown.
- When supplied, put the gym and the specific machine in `gym` and `machine` on each relevant set. These are exact identifiers, not guessed labels. If the user states the number excludes the bar, set `load_basis` to `plates_only`; use `total` only when total weight is explicit, otherwise leave it null. Preserve legacy notes. Never invent bar weight or machine identity.
- Use `duration_min` and `distance_km` for timed holds and measured carries as described in the parsing rules. Use `pace` and `avg_hr` for cardio.
- Manual `/log` rows do not include `laps`. The old `Laps` column was retired in 2026-05; swim lap counts now live exclusively on the imported `<Person>/data/swimming/YYYY.MM.workouts.csv`. There is no per-lap file — see "Apple Health refresh".
- Monthly CSV schema v2 appends `Gym | Machine | Load Basis` to the original 18 columns: `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR | Active Cal | Total Cal | Elevation (m) | Elapsed | Source`. SESSION is filled in by `canonicalize_monthly_csv` (per-month session number repeated on every row of the same date); leave it out of the row dict. Source is filled by the writer/importer.
- Sort rows in the JSON by date ascending, then `num`, then `set`. The script does not re-sort.

## Rules

- No coaching. No suggestions. No opinions.
- One clarifying question max if input is genuinely unreadable.
- Never invent data.
- No narration. Don't show parsing steps, intermediate summaries, or thinking out loud. Go directly from input to script call to summary line.
