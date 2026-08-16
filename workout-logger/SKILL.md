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

Both are HealthAutoExport-backed — there is one importer and one source.
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

1. Parse the message into row dicts — one per set — using the references above. Collect the set of dates touched by this log. If the message contains an explicit bodyweight line (see parsing rules), also parse that into a bodyweight entry. If the user includes `CSS test` on the header line of a 400m + 200m TT pair (see parsing rules), parse the two times and assemble a `css_test` payload field. If the message contains an explicit sleep line (see parsing rules), parse that into a `sleep` entry keyed to the session's date. If the message contains explicit `sauna` and/or `cold` lines, including the coach-plan `Recovery:` placeholder line filled with sauna/cold text (see parsing rules), parse them into `thermal` entries — a `sauna` + `cold` pair under the same workout header pairs into one entry; standalone lines become their own entry. If the message contains explicit light-therapy lines (`rlt`, `red light`, `near-ir`, `blue light`, `pbm`, `light therapy`, etc., see parsing rules), parse them into `light_therapy` entries keyed to the session's date — independent of any thermal entry on the same date.

   **Unknown-exercise gate (REQUIRED before building the payload).** For every distinct exercise name in the parsed rows, run `python3 Skills/shared/exercises_database.py lookup "<name>"`. The script consults both the canonical catalog and the alias table (case-insensitive). Three branches:

   - **Exit 0** with a canonical name printed → use that canonical name (which may differ from what the user typed by case, modifier handling, or alias). Replace the row's `exercise` value with the canonical form. Continue.
   - **Exit 1 (`UNKNOWN`)** AND `python3 Skills/shared/exercises_database.py fuzzy "<name>"` returns a top-1 hit with similarity ≥ 0.85 → high-confidence alias candidate. Show the user once via `AskUserQuestion`: "Looks like `<typed name>` is a typo of `<canonical>` (similarity X.XX). Add as alias?" Options: `Yes, add alias` / `No, this is a different exercise` / `Skip — log under the typed name`. **This prompt overrides auto-mode/default-mode assumptions; the user is the catalog-corruption guard, even for obvious plural/singular typos. Never write an alias without explicit approval.** On `Yes`, pipe `{"kind":"alias","user_input":"<typed>","canonical_name":"<canonical>"}` to `python3 Skills/shared/exercises_database.py propose --from-stdin`, then replace the row's exercise with the canonical form and continue. On `No`, fall through to the next branch (full research). On `Skip`, leave the row untouched (it will silently contribute zero volume in the coach; flag this in the run summary so the user can fix later).
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
     "sleep": [ {"date": "YYYY-MM-DD", "total_h": 7.5, "deep_h": 1.2, "rem_h": 1.3,
                 "core_h": null, "unspecified_h": null, "awake_h": null,
                 "time_in_bed_h": 8.4, "efficiency_pct": null, "notes": null}, ... ],
     "thermal": [ {"date": "YYYY-MM-DD", "start": "18:30",
                   "heat_type": "dry", "heat_temp_c": 85,
                   "heat_rounds": 2, "heat_round_durations_min": [12, 8],
                   "cold_type": "cold_air", "cold_duration_sec": 300,
                   "cold_temp_c": null, "notes": null}, ... ],
     "light_therapy": [ {"date": "YYYY-MM-DD", "start": null,
                         "duration_min": 5, "light_type": "red+ir",
                         "wavelength_nm": null, "body_area": "full_body",
                         "modality": "cabin", "ambient_temp_c": 45,
                         "notes": null}, ... ],
     "css_test": {"date": "YYYY-MM-DD", "t400_sec": 450, "t200_sec": 210}
   }
   ```
   Omit `bodyweight` entirely (or send `[]`) if the user didn't mention a weight. **Never prompt for it.** Omit `sleep` entirely if the user didn't include a sleep line — **never prompt for sleep**. Omit `thermal` entirely if the user didn't include a `sauna` / `cold` line — **never prompt for thermal**. Omit `light_therapy` entirely if the user didn't include a light-therapy line — **never prompt for light therapy**. Omit `css_test` unless the user explicitly typed `CSS test` — never infer it. Per-lap swim data (Stroke / SWOLF / per-lap pace) cannot be entered manually, and no import supplies it either — HealthAutoExport carries no lap payload, so `swimming/*.laps.csv` is never written and `Avg SWOLF` / `Stroke Mix` stay blank. Per-night segment metadata also can't be entered manually: `first_segment_start` / `last_segment_end` come from the importer, and `n_segments` is permanently blank on every row.
3. Run `python3 scripts/append_workout.py --person <Person> /tmp/workout_payload.json` (where `<Person>` is the resolved name, e.g. `<Person>` or `<OtherPerson>`). The script routes rows to the right `monthly/YYYY.MM.csv` under `<Person>/data/`, calls `canonicalize_monthly_csv` (sort + recompute Volume / Pace / SESSION + rebuild TOTAL rows), mirrors any bodyweight entries into `<Person>/data/health_metrics.csv` (sparse-merge — never overwrites other metrics on that date), dual-writes any sleep entries into both `<Person>/data/sleep/YYYY.MM.nights.csv` (rich per-night detail) and `<Person>/data/health_metrics.csv` (headline Total/Deep/REM/Time in Bed for the recovery score), writes any thermal entries to `<Person>/data/thermal/YYYY.MM.sessions.csv` (sparse-merge; `heat_total_min` auto-derived from the per-round durations), and writes any light-therapy entries to `<Person>/data/light_therapy/YYYY.MM.sessions.csv` (sparse-merge; `modality` auto-defaults to `cabin` when `ambient_temp_c ≥ 30`). Sleep Efficiency is auto-derived inside the upsert when both Total and Time in Bed are present.
4. **Verify the write succeeded.** Capture the script's stdout and exit code:
   - If the exit code is non-zero, print the exact stderr output and stop. Do not report success.
   - If workout `rows` were present and the exit code is 0 but stdout does not contain the word `Appended`, print the exact stdout and stop with: "Unexpected script output — please check the tracker manually."
   - If no workout `rows` were present, a successful `Bodyweight:`, `Sleep Nights:`, `Thermal Sessions:`, `Light Therapy:`, `Nutrition Phases:`, or `CSS:` line confirms the write.
   - If stdout contains `Appended`, the workout-row write is confirmed. Proceed.
5. Print the summary line before moving on to Apple Health refresh or verification: `N workouts, N exercises, N total sets, Wkg total volume`. If any session was marked as a deload, append ` (deload session)`. If one or more weights were logged, append ` | morning weight: 78.4kg` (or comma-separate multiple dates). The summary comes from the script's `Appended …` stdout line — extract N rows and dates from it. Do not skip this in test runs; if you are validating a `/log` flow, emit the same summary a real `/log` invocation would have emitted.

6. **Apple Health refresh (automatic — no prompts at all).** After printing the summary line, ALWAYS run the importer for the resolved person. There is nothing to ask about: the user drops a fresh export every time they log, so the refresh is unconditional.

   ```
   python3 Skills/shared/import_health_auto_export.py --person <Person>
   ```

   That is the only importer. It auto-resolves the export from the workout-tracker root (one above the per-person folders): `./HealthAutoExport*.zip`, **most recent by mtime wins**. There is no second file shape and no dispatch decision to make.

   If no zip is there, the importer prints `ERROR: HealthAutoExport ZIP not found: HealthAutoExport*.zip` and exits 1 — surface that one line to the user and finish. A missing export just means the user didn't drop one this time.

   It defaults to 6 months back, so `/log` passes `--person` and nothing else. The full flag set, for the rare hand-run: `--person`, `--zip`, `--since`, `--until`, `--allow-past-months`, `--replace-range`, `--dry-run`, `--keep-export`.

   Capture stdout and append the importer's `Health Metrics: …`, `Sleep Nights: …`, `Swim Workouts: …`, and `Workout Sessions: …` summary lines (plus any `Auto-cardio: …` / `Strength clustering warnings:` / `Profile: …` / `Deleted source export: …` / `Committed <Person> data: …` lines) to the user-facing summary printed in step 5. Relay `manual-wins warnings`, skipped-negligible-swim lines, and nearby-swim notes too; those are user-facing data-quality decisions, not debug noise.

   The refresh runs on every `/log` invocation automatically. Idempotent re-runs are fine — the importer's sparse-merge protects existing data, so refreshing when nothing changed is a harmless no-op.

The tracker itself is the output. No markdown tables, no files presented, no narration.

## Apple Health refresh

The logger never imports Apple Health on its own — it shells out to
`Skills/shared/import_health_auto_export.py`, which is **the only importer**.
It takes `HealthAutoExport*.zip` and covers the full tracker surface: VO2max,
RHR, HRV, walking HR, wrist temp, breathing disturbances, exercise minutes,
steps, active / basal energy, sleep stages, per-workout HR, and per-workout
swim aggregates. The native Apple XML importer is retired; `Export*.zip` is
not a path any more.

Inside the archive, the member selects the reader: a `HealthAutoExport-*.json`
member picks the JSON reader (the supported format), and anything else falls
back to the deprecated CSV reader with a warning on stderr. Route GPX files
inside the archive are ignored.

It writes into the per-person CSV store under `<Person>/data/`:

- `health_metrics.csv` — 22 columns of daily aggregates, including the headline sleep fields (Sleep Total / Deep / REM / Time in Bed) and, appended immediately before `Notes`, `Steps` / `Active Energy (kcal)` / `Basal Energy (kcal)`. Cells the export can't fill stay None; sparse-merge protects existing values.
- `workout_sessions.csv` — one row per Apple `Workout`, HR columns populated.
- `swimming/YYYY.MM.workouts.csv` — per-swim aggregates: Pool Length, Laps, Strokes, SPL, Location, Water Temp, distance. **No `swimming/YYYY.MM.laps.csv` is written.** HealthAutoExport carries no per-lap payload, so per-lap detail and SWOLF are permanently unavailable and `Avg SWOLF` / `Stroke Mix` stay blank on new rows. Any existing `laps.csv` is frozen XML-era history.
- `sleep/YYYY.MM.nights.csv` — per-night sleep architecture: all stages the export exposes (Total, Core, Deep, REM, Unspecified, Awake) plus Time in Bed, Sleep Efficiency (derived), and First/Last Segment clock times (bedtime / wake-up schedule). `N Segments` is **permanently blank** — HealthAutoExport reports one aggregate row per night, with no segment breakdown to count.

It also creates / reads `<Person>/data/profile.csv`, a 2-column key/value file pinning the per-tracker `source` (`health_auto_export` is the only accepted value; the older source names were removed with the importers that wrote them), `auto_cardio` flag, `birthday`, and the swim CSS keys (`swim_css_sec_per_100m`, `swim_css_set_at`, `swim_pool_length_default`). The coach's `read_tracker.py` reads this to decide which sections of the report it can fill.

**What the import cannot see.** Apple's 1-10 per-workout effort score is gone permanently — `metadata` is empty on every JSON workout — so there is no RIR / RPE intake from the import path at all. Treat that as a permanent property of the source, not a provisional gap waiting on a better export. Per-lap swim detail and SWOLF are permanently out of reach for the same reason.

**File naming.** Drop the app-generated `HealthAutoExport*.zip` into the workout tracker folder. Don't rename it — the resolver globs by pattern and picks the most recent by mtime.

**Idempotency.** Re-running with the same export is a no-op. Sparse-merge upserts protect existing values — incoming `None` never overwrites a populated cell, so a partial export (e.g. just last week) won't erase older history.

**The consumed export is deleted, not archived.** On success the importer deletes the zip it just read; `--keep-export` is the escape hatch when someone wants the file kept. `<root>/.processed/` is **retired and empty** — it is no longer the safety net, so don't describe it as one. Rollback is git instead: each person's `data/` directory is its own git repository (`shared/data_git.py`), and both `append_workout.py` and the importer commit automatically after every confirmed write — one commit per operation, message `log: <N> rows, <dates>` or `import: <zip name>`.

**Auto-cardio.** When the importer ingests cardio workouts (Running, Hiking, Cycling, Swimming, HIIT) AND `auto_cardio` in `profile.csv` is True, those workouts also flow into the matching `<Person>/data/monthly/YYYY.MM.csv` as cardio rows carrying an `apple` / `gymkit:<Device>` value in the typed `Source` column. Manually-logged rows always win — the dedupe rule (date + exercise + duration ±1 min) skips Apple workouts that match an existing manual entry. Default: `auto_cardio = true`. Flip to `false` per-tracker by editing `profile.csv` if a user prefers manual-only logging.

**Step 6 always refreshes, and never asks.** No watchers, no cron, and no prompt of any kind: run the importer for the resolved person, append its summary to the user-facing output, and finish. If no export is in the folder, surface the importer's one-line `ERROR: HealthAutoExport ZIP not found: …` and finish. With a single source there is no source decision left to put to the user — the health refresh is fully silent.

## Bodyweight (opt-in)

Bodyweight is opt-in. Record it only when the user explicitly includes it in the `/log` message — see `references/parsing-rules.md` for the accepted formats. No automatic prompts, no probing for missing weights, no `AskUserQuestion`. If the user didn't mention a weight, don't record one.

The standing convention is **morning, empty stomach**. If the user writes something that implies a non-morning context (e.g. "after dinner"), include that in the entry's `notes` field (e.g. `"evening, not fasted"`).

### Bulk-seed (historical import)

To back-fill many historical weights at once, call `append_workout.py` with a payload of only bodyweight entries: `{"rows": [], "bodyweight": [{"date": "...", "kg": ..., "notes": null}, ...]}`. The logger forwards each entry into `<person>/data/health_metrics.csv` via the sparse-merge `upsert_health_metrics` — same dedupe-by-date semantics, but the bodyweight is now stored on the Health Metrics row (col B) alongside the rest of that day's metrics.

## Sleep (opt-in)

Sleep is opt-in. Record it only when the user explicitly includes a sleep line in the `/log` message — see `references/parsing-rules.md` for the accepted formats. **No automatic prompts, no probing for missing sleep, no `AskUserQuestion`.** If the user didn't mention sleep, don't record it.

Sleep entries are dual-written by `append_workout.py`:

- **Rich detail** → `<person>/data/sleep/YYYY.MM.nights.csv` via the sparse-merge `upsert_sleep_nights`. Captures all 6 stages Apple exposes (Total, Core, Deep, REM, Unspecified, Awake) plus Time in Bed, derived Sleep Efficiency, and first/last segment clock times. Manual entries leave the segment-metadata columns blank — only the importer populates those, and `N Segments` stays blank even then, because HealthAutoExport reports one aggregate row per night with nothing to count.
- **Headline mirror** → `<person>/data/health_metrics.csv`, columns Sleep Total / Sleep Deep / Sleep REM / Time in Bed. Sparse-merge protects every other metric on the same date. This is the path the coach's `recovery_score` already reads, so a manual sleep entry flows into the recovery score on the next `/coach` run.

If the user supplies only partial sleep info (e.g. just `sleep 7h30`), sparse-merge keeps the existing Apple-imported deep/REM/in-bed values on that date untouched and only updates the field(s) the user provided. The reverse is also true: a subsequent Apple import that fills in the missing fields won't overwrite the user's manual `total_h`.

Sleep Efficiency is auto-derived inside the upsert when both `total_h` and `time_in_bed_h` are present and `efficiency_pct` wasn't supplied as a manual override.

### Bulk-seed (historical sleep import)

To back-fill many historical sleep nights at once, call `append_workout.py` with a payload of only sleep entries: `{"rows": [], "bodyweight": [], "sleep": [{"date": "...", "total_h": ..., ...}, ...]}`. The logger routes each entry to the right `sleep/YYYY.MM.nights.csv` and mirrors the headline fields into `health_metrics.csv`. Same dedupe-by-date semantics as bodyweight.

The HealthAutoExport import populates the `sleep/` folder when sleep-stage data exists. Manual sleep entries still dual-write there on demand, and the coach's stage-aware report sections gate on capabilities plus data presence so the user-facing output stays coherent.

## Sauna + cold exposure (opt-in)

Sauna and cold exposure are opt-in. The user includes a `sauna` and/or `cold` line in the `/log` message — see `references/parsing-rules.md` for the syntax (plus-shorthand for multi-round saunas, the 5-option cold-type enum, pairing rules). **No automatic prompts, no probing, no `AskUserQuestion`** — with one narrow exception: outdoor temperature on `cold_air` (see "Outdoor temperature" below). Absent ≡ didn't happen for everything else.

Thermal entries are written to `<Person>/data/thermal/YYYY.MM.sessions.csv` (manual-/log-only — Apple Health doesn't classify sauna sessions reliably, so there's no importer-side write path). Sparse-merge by `(date, start, heat_type, cold_type)`; `Notes` is manual-wins. The wider key prevents same-day unspecified-time sauna and cold entries from overwriting each other. `heat_total_min` and (when absent) `heat_rounds` are auto-derived from `heat_round_durations_min` inside `upsert_thermal_sessions` so the file is internally consistent.

**Pairing.** A `sauna` line and a `cold` line under the same workout's header become **one row** (one protocol session). Standalone cold (e.g. morning cold shower without sauna) lives in its own row with heat columns blank. Two sessions with the same date, blank start, and the same heat/cold types still intentionally merge; add a `start` time when the user truly did two same-type protocols on the same day.

**Outdoor temperature — narrow exception to the no-prompt rule.** Cold exposure outdoors at −5°C is a fundamentally different stimulus than cold exposure outdoors at 25°C, so the number has to be recorded. It can only come from the user because **a standalone sauna or cold-air session is not a workout** — no workout record exists to carry its ambient temperature. (The import does read `temperature` and `humidity` off actual workouts, in clean °C, on nearly all of them; the gap is the session type, not the field.) When the parsed payload contains a `cold_air` entry with `cold_temp_c` null, **ask once** in chat — one short question, before the write:

> *"You logged a cold-air session — roughly what was it outside? (give a number in °C, or say `skip`)"*

Rules for this ask:
- **Only when `cold_type == "cold_air"`** AND `cold_temp_c` is null. Never ask for `cold_plunge` / `cold_water` / `cold_shower` (those temperatures are usually known from the protocol or irrelevant).
- **Only when the user actually typed a `cold` line in this `/log` message.** Don't ask about cold entries that came in via a bulk-seed payload — those are historical and the user is filling in many at once.
- **Once per log call, per cold_air entry.** If the user says `skip`, write the entry with `cold_temp_c=null` and proceed; don't re-ask on a subsequent `/log`.
- Accept a number (`-2`, `12.5`, `0`) or `skip`. If the answer isn't parseable, treat as `skip`.

This is the only thermal-field prompt allowed. All other heat / cold fields remain absent-≡-didn't-happen.

### Bulk-seed (historical thermal import)

To back-fill historical thermal sessions, call `append_workout.py` with a payload of only thermal entries: `{"rows": [], "thermal": [{"date": "...", "heat_type": "dry", "heat_round_durations_min": [12], "heat_temp_c": 85, "cold_type": "cold_air", "cold_duration_sec": 300}, ...]}`. The logger routes each entry to the right `thermal/YYYY.MM.sessions.csv`. Same sparse-merge semantics as normal `/log` thermal writes: dedupe by `(date, start, heat_type, cold_type)`.

## Light therapy (opt-in)

Light therapy is opt-in. The user includes a light-therapy line (`rlt`, `red light`, `near-ir`, `blue light`, `pbm`, `light therapy`, etc.) in the `/log` message — see `references/parsing-rules.md` for the syntax (keyword → light_type defaults, optional wavelength / ambient temp / body area / modality, alias tables). **No automatic prompts, no probing, no `AskUserQuestion`.** Absent ≡ didn't happen.

The module is broad on purpose: it stores red-light cabins, near-IR probes, blue-light SAD lamps, and any future photobiomodulation modality under one schema. Pick the keyword that matches what the user wrote and let the upsert apply the defaults.

Light-therapy entries are written to `<Person>/data/light_therapy/YYYY.MM.sessions.csv` (manual-/log-only — Apple Health doesn't classify light-therapy sessions). Sparse-merge by `(date, start)`; `Notes` is manual-wins. `modality` is auto-defaulted to `cabin` inside `upsert_light_therapy_sessions` when `ambient_temp_c ≥ 30` and the user didn't specify a modality (heated walk-in inference).

**No pairing with thermal.** A sauna+RLT session in real life lands as **two payload entries** (one in `thermal`, one in `light_therapy`), both keyed to the same date. They live in two stores. If the user actually used a sauna-integrated red-light panel, set `modality: "sauna_integrated"` on the light-therapy entry.

### Bulk-seed (historical light-therapy import)

To back-fill historical light-therapy sessions, call `append_workout.py` with a payload of only light-therapy entries: `{"rows": [], "light_therapy": [{"date": "...", "duration_min": 5, "light_type": "red+ir", "ambient_temp_c": 45}, ...]}`. The logger routes each entry to the right `light_therapy/YYYY.MM.sessions.csv`. Same dedupe-by-`(date, start)` semantics as the per-month thermal store.

## Nutrition phase (opt-in)

Nutrition phases (`bulk` / `cut` / `maintain` / `recomp`) are opt-in. The user signals one via a top-level line in the `/log` message:

- **`bulking start [date] [target X kcal] [protein X g/kg] [rate X kg/wk] [stop: ...]`** — opens a new phase. `date` defaults to today; all other targets are optional and fall back to the bulk defaults (target rate 0.25 kg/wk; coach uses bulking-science.md for kcal/protein when omitted). `stop:` is a free-text pre-commitment line listing the off-ramp conditions (e.g. `stop: >0.5 kg/wk for 3 weeks; lifts stall 2 weeks; visible bloat`).
- **`bulking end [date]`** — closes the open bulk phase. `date` defaults to today.
- **`bulking update [field=value ...]`** — updates the open bulk phase's targets / notes. Same keys as start (target, protein, rate, stop, notes).
- The same three commands exist for `cutting` (e.g. `cutting start`, defaults: target rate -0.5 kg/wk) and `maintaining` (target rate 0.0) and `recomp` (no target rate).

**No automatic prompts, no probing, no `AskUserQuestion`.** Absent ≡ didn't happen.

Phases are stored in a single flat CSV at `<Person>/data/nutrition_phases.csv` (sparse: a handful of rows per year, so no per-month split). Dedupe key = `Start Date` (one phase per start_date). Opening a new phase while one is already open is allowed — both rows exist, and the coach's `nutrition_phase_summary` picks the most recent open phase. To "swap" phases cleanly, end the prior one first (`bulking end`) then start the new one.

Payload shape — add a `nutrition_phase` key alongside `rows` / `bodyweight` / `sleep` / `thermal` / `light_therapy`:

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
      "target_rate_kg_per_wk": 0.25,
      "stop_conditions": ">+0.5 kg/wk for 3 weeks; lifts stall 2 weeks; visible bloat",
      "notes": "first bulk after 4-month maintain"
    }
  ]
}
```

The logger calls `csv_store.upsert_nutrition_phases(person, payload["nutrition_phase"])` which sparse-merges on `Start Date`. Phase-type validation lives in the upsert (one of `bulk` / `cut` / `maintain` / `recomp`); unknown values raise ValueError. Coach reads via `read_nutrition_phases` and the lib helper `nutrition_phase_summary`.

The coach evaluates whether the bulk is on-track by reading bodyweight rate from `health_metrics.csv` (smoothed-endpoint 14d window) — daily macro logging is NOT required. Phase metadata alone gives the coaching signal.

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
  "distance_km": null,
  "duration_min": null,
  "pace": null,
  "avg_hr": null
}
```

Rules:
- `num` restarts at 1 for each new date. All sets of the same exercise share a `num`.
- `set` is 1, 2, 3 within an exercise.
- Do NOT compute or include a `volume` field — `canonicalize_monthly_csv` recomputes Volume = reps × kg on every write and writes a literal sum on the TOTAL row. Skip the arithmetic.
- The cardio fields (`distance_km`, `duration_min`, `pace`, `avg_hr`) are cardio-only. Leave null for strength rows.
- Manual `/log` rows do not include `laps`. The old `Laps` column was retired in 2026-05; swim lap counts now live exclusively on the imported `<Person>/data/swimming/YYYY.MM.workouts.csv`. There is no per-lap file — see "Apple Health refresh".
- The monthly CSVs have 18 columns: `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR | Active Cal | Total Cal | Elevation (m) | Elapsed | Source`. SESSION is filled in by `canonicalize_monthly_csv` (per-month session number repeated on every row of the same date); leave it out of the row dict. Source is filled by the writer/importer.
- Sort rows in the JSON by date ascending, then `num`, then `set`. The script does not re-sort.

## Rules

- No coaching. No suggestions. No opinions.
- One clarifying question max if input is genuinely unreadable.
- Never invent data.
- No narration. Don't show parsing steps, intermediate summaries, or thinking out loud. Go directly from input to script call to summary line.
