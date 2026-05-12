# Parsing Rules

## Date

`DD.MM` → `YYYY-MM-DD` using current year. If omitted, ask once.

## Fields

- **#**: One number per exercise. All sets of the same exercise share the number.
- **Set**: 1, 2, 3... per exercise
- **kg**: 0 if no weight. `k` = `kg`. `lbs` or `lb` → divide by 2.205, round to nearest 0.5.
- **Volume**: Reps × kg
- **Reps**: 0 for carries, walks, holds, isometric positions. Put the duration in the `duration_min` field (accepts `MM:SS` or decimal minutes) so the coach can read it structurally. Put distance in `distance_km` when the exercise tracks distance (farmer walks, loaded carries). Use Notes only for qualitative detail like "per hand" or "beltless".
- **Notes**: Only from parenthetical input like `(felt heavy)`. Never invent notes. Exception: `Deload Workout` on any row of the session when the header line contains the `deload` keyword — the styler hoists it to the session's TOTAL row (see "Session-level flags" below).

## Multi-Set Separator

`///`, `//`, or `/` all mean separate rows.

## Rep × Weight Formats

All equivalent: `8 x 56kg` · `56kg x 8` · `8x56k` · `8 @ 56` · `56 for 8`

Assign the larger number to kg and smaller to reps unless context makes it obvious (e.g. `50 jumping jacks` → 50 reps, 0 kg).

## Name Matching Priority

The output name must ALWAYS be a canonical name from `../../shared/exercises-database.md`, in the exact casing it appears there. Never pass through the user's original casing. Work down this ladder — stop at the first hit:

1. **Exact match** (case-insensitive) → use database casing, no Notes annotation.
2. **Known alias** → check `aliases.md`, use canonical name, no Notes annotation.
3. **Substring match** → input contained in canonical name or vice versa, resolved with equipment context (e.g. `incline press` + no equipment word + user context → `Incline Chest Press Machine`). No Notes annotation.
4. **Equipment-qualified fuzzy** → if the input contains an equipment word (`cable`, `dumbbell`, `machine`, `barbell`), prefer the canonical name that has both that equipment word and the highest string-similarity to the rest. Use it and add Notes: `fuzzy match from: "user's input"`.
5. **difflib fuzzy match** → apply `difflib.get_close_matches(user_input.lower(), [name.lower() for name in canonical_names], n=1, cutoff=0.7)`. If there's a hit, use that canonical name (in its database casing) and add Notes: `fuzzy match from: "user's input"`. You can do the ratio in your head for obvious cases; for borderline ones run the inline snippet.
6. **No close match** → user's name in title case, and add Notes: `(not in database)` so it stands out on review.

**Mental shortcut for the fuzzy step:** if you'd reliably recognize the typo as the canonical exercise at a glance (`flat benchpres` → `Flat Bench Press`, `squatt` → `Squat`), treat it as a fuzzy match with high confidence. If you'd genuinely not know which exercise the user meant, fall through to step 6 rather than guessing.

Never invent exercise names. Fuzzy match only picks from the canonical list.

## Session-level flags

If the word `deload` appears anywhere on the `/log` header line (before the first exercise bullet), put `Deload Workout` in the `notes` field of any row of that session. The styler relocates the marker onto the session's `TOTAL` row Notes column (alongside Avg HR, Active Cal, Duration, etc.) — that's where the coach reads it from. Don't try to merge with per-exercise warmup notes; user comments stay on their row, the deload marker rides on TOTAL.

## Cardio

Extended columns activate for the entire workout if any cardio row is present.

| Field | Format | Example |
|---|---|---|
| Duration | `MM:SS` | `41:29` |
| Pace | `MM:SS` min/km | `10:16` |
| Distance | km | `5` |
| Avg HR | bpm | `155` |

Convert pace input: `8'53"` → `8:53`. Never use decimal for time fields.
Leave fields blank if not provided.

**Distance unit:** the tracker stores distance in km. If the user writes `Swim 550m` or `Run 800m`, convert (`550m` → `0.55`, `800m` → `0.8`). The Apple Health importer is unit-aware (reads the `unit` attribute from the XML) — never log `550` for a 550 m swim, that landed as `550 km` in the historical bug.

**Laps (swim) — no longer manually written.** The old `Laps` column on the monthly CSV was retired in 2026-05. Swim lap counts now live exclusively on `<Person>/data/swimming/YYYY.MM.workouts.csv`, populated by the Apple Health importer. If the user types `<N> laps` / `<N> lengths` / `<N> Bahnen` on a swim row, the parser may silently ignore it — the value has nowhere to go through `/log`, and the Apple importer will fill the canonical count post-hoc on the matching session.

**Per-lap swim detail (Stroke / SWOLF / per-lap pace) is NOT manually parseable.** Apple Health is the only source — the importer reads `HKWorkoutEventTypeLap` events and writes them to `<Person>/data/swimming/YYYY.MM.laps.csv`. A manual `/log` swim row records distance + duration only.

## CSS test (Critical Swim Speed)

When the user types `CSS test` on the header line of a `/log` message that contains a 400m + 200m time-trial pair on the same date, also produce a top-level `css_test` field on the payload wrapper:

```json
{
  "rows": [ ... two swim rows for 400m and 200m ... ],
  "css_test": {"date": "YYYY-MM-DD", "t400_sec": 450, "t200_sec": 210}
}
```

- `date` is the session date.
- `t400_sec` / `t200_sec` are the durations of each TT in seconds (convert MM:SS → seconds).
- The script computes `(t400_sec - t200_sec) / 2` (sec/100m) and writes `swim_css_sec_per_100m` + `swim_css_set_at` to `<Person>/data/profile.csv`.

Only emit `css_test` when the user explicitly types `CSS test` on the header. Never infer it from a 400+200 pair logged without that keyword — silent CSS overwrites surprise the user. The two TT swims still get logged as normal swim rows on the monthly CSV.

## Bodyweight (opt-in)

If (and only if) the `/log` message contains an explicit bodyweight line, parse it into a `bodyweight` entry keyed to the session's date. Accepted forms (case-insensitive):

- `weight 76.5`, `weight: 76.5`, `weight 76.5 kg`
- `bw 76.5`, `bw: 76.5kg`
- `bodyweight 76.5`, `bodyweight: 76.5`

Default `notes` to `null`. Only set `notes` when the user gave an explicit non-morning context on the same line (e.g. `weight 77.1 after dinner` → `"evening, not fasted"`). The standing convention is **morning, empty stomach**, so a bare number needs no note.

For multi-date logs, attach the weight to the date on whose header line it appears. If the user wrote the weight on the top-level `/log` header, attach it to every date in the message.

Never invent or guess a weight. If no bodyweight line is present, omit `bodyweight` from the payload entirely.

## Sleep (opt-in)

If (and only if) the `/log` message contains an explicit sleep line, parse it into a `sleep` entry keyed to the session's date (the wake-up date — same date the workout happened, since the sleep precedes the morning workout). All forms case-insensitive.

**Bare duration** (`sleep <duration>`) → writes `total_h` only:

- `sleep 7h25`, `sleep 7:25`, `sleep 7.42h`, `sleep 7.42`, `sleep 450m`, `sleep 450 min`

**Per-stage breakdown** (`sleep [total <h>] [core <h>] [deep <h>] [rem <h>] [unspecified <h>] [awake <h>] [inbed <h>] [efficiency <pct>]`) → writes each named stage:

- `sleep total 7.5 deep 1.2 rem 1.3`
- `sleep total 7.5 deep 1.2 rem 1.3 core 4.5 awake 0.6 inbed 8.4`
- `inbed 8.4` (standalone, writes only `time_in_bed_h`)
- `efficiency 91` (standalone, writes only `efficiency_pct` as a manual override)

Time grammar (each duration): `7h25` (h+m), `7:25` (h:m), `7.42h` or `7.42` (decimal hours), `450m` or `450 min` (minutes). All convert to decimal hours.

Field aliases (case-insensitive): `light` → `core`, `waso` → `awake`, `tib` → `inbed`, `eff` → `efficiency`.

The payload entry shape:

```json
{
  "date": "2026-05-12",
  "total_h": 7.5,
  "core_h": 4.5,
  "deep_h": 1.2,
  "rem_h": 1.3,
  "unspecified_h": null,
  "awake_h": 0.6,
  "time_in_bed_h": 8.4,
  "efficiency_pct": null,
  "notes": null
}
```

Omit any field the user didn't type — sparse-merge applies, so partial input is fine. Sleep Efficiency is auto-derived inside the upsert when both `total_h` and `time_in_bed_h` are present and `efficiency_pct` wasn't supplied. Default `notes` to `null` — only set it for an explicit user-supplied annotation on the same line (e.g. `sleep 6h woke up 3am` → `"woke up 3am"`).

For multi-date logs, attach the sleep entry to the date on whose header line it appears. If the user wrote the sleep line on the top-level `/log` header, attach it to every date in the message.

Never invent or guess sleep numbers. If no sleep line is present, omit `sleep` from the payload entirely. Never prompt for missing sleep data.

## Sauna + cold exposure (opt-in)

If (and only if) the `/log` message contains an explicit `sauna` or `cold` line, parse it into a `thermal` entry keyed to that session's date. All forms case-insensitive. **Absent ≡ didn't happen** — if no sauna / cold line appears, omit `thermal` from the payload entirely. **Never prompt.**

### Sauna line

`sauna <duration>[+<duration>...]min [<temp>C] [<type>]`

| Form | Writes |
|---|---|
| `sauna 12min` | one round, no temp / type |
| `sauna 12min 85C` | with temp |
| `sauna 12+8min 85C` | two rounds (12 + 8 minutes), one row with `heat_round_durations_min: [12, 8]` |
| `sauna 12+8+5min 85C dry` | three rounds, explicit type |

- **Plus-shorthand for multi-round saunas.** `12+8min` means two rounds: 12 minutes + 8 minutes. The schema stores per-round durations on one row (NOT one row per round). The total is auto-derived.
- **Heat types (case-insensitive):** `dry` (default), `steam`, `infrared` / `IR`, `banya`. Anything else falls through to `dry`.
- **Temperature:** integer Celsius, suffixed `C` (e.g. `85C`). Optional.

### Cold line

`cold <duration><unit> <type> [<temp>C]`

| Form | Writes |
|---|---|
| `cold 30s shower` | cold_shower, 30 seconds |
| `cold 5min air` | cold_air, 5 minutes (= 300 seconds) |
| `cold 5min air 4C` | cold_air with ambient temp |
| `cold 90s plunge 8C` | cold_plunge with water temp |
| `cold 12min water 14C` | open-water swim / lake / sea |

- **Cold types (case-insensitive aliases):**
  - `air` / `outside` / `outdoor` → `cold_air`
  - `shower` → `cold_shower`
  - `plunge` / `bath` / `ice` → `cold_plunge`
  - `water` / `lake` / `sea` / `swim` → `cold_water`
- **Duration unit:** `s` / `sec` / `seconds` stays in seconds (typical for showers); `m` / `min` / `minutes` converts to seconds (×60). The store column is `cold_duration_sec`.
- **Temperature:** integer Celsius, optional. Ambient air temp for `cold_air`; water temp for `cold_shower` / `cold_plunge` / `cold_water`.

### Pairing rule

A `sauna` line and a `cold` line under the same workout's header within one `/log` message become **one row** in `thermal/YYYY.MM.sessions.csv` — they're assumed to be one protocol session (sauna → cold).

Force separate rows by placing them under different workout headers (e.g. a morning standalone cold shower + an evening post-workout sauna+cold = two rows for that date).

### Payload entry shape (one row → one entry)

```json
{
  "date": "2026-05-12",
  "start": "18:30",
  "heat_type": "dry",
  "heat_temp_c": 85,
  "heat_rounds": 2,
  "heat_round_durations_min": [12, 8],
  "cold_type": "cold_air",
  "cold_duration_sec": 300,
  "cold_temp_c": null,
  "notes": null
}
```

Omit any field the user didn't provide — sparse-merge applies. `heat_rounds` and `heat_total_min` are auto-derived from `heat_round_durations_min` inside `upsert_thermal_sessions` (don't bother computing them client-side). Default `notes` to `null` — only set it for an explicit user annotation on the same line (e.g. `sauna 10min 85C dry; felt overheated` → `"felt overheated"`).

### Date attachment

For multi-date logs, attach the thermal entry to the date on whose header line the sauna / cold line appears. If the user wrote it on the top-level `/log` header, attach to every date in the message (rare; typically one heat session per workout day).

Never invent sauna or cold sessions. Never prompt for missing data. If the user didn't type a sauna / cold line, they didn't do one — no row.
