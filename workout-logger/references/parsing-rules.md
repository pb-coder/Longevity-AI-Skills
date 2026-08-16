# Parsing Rules

## Date

`DD.MM` → `YYYY-MM-DD` using current year. If omitted, ask once.

A pasted `Date:` line from a coach plan may end with a trailing backslash
(`Date: 2026-06-05\`) — that's a Markdown hard-break marker the plan uses to
keep `Date:` and `Recovery:` on separate lines, not part of the value. Strip a
trailing backslash (and surrounding whitespace) before parsing. The same
applies to a pasted `Recovery:` line.

## Fields

- **#**: One number per exercise. All sets of the same exercise share the number.
- **Set**: 1, 2, 3... per exercise
- **kg**: 0 if no weight. `k` = `kg`. `lbs` or `lb` → divide by 2.205, round to nearest 0.5.
- **Volume**: Reps × kg
- **Reps**: 0 for carries, walks, holds, isometric positions. The duration MUST go in `duration_min` — see "Holds and carries" below. Put distance in `distance_km` when the exercise tracks distance (farmer walks, loaded carries). Use Notes only for qualitative detail like "per hand" or "beltless".
- **Notes**: Only from parenthetical input like `(felt heavy)`. Never invent notes. **Never put a duration, a hold time, or a carry distance in Notes** — those are typed columns (see "Holds and carries"). Exception: `Deload Workout` on any row of the session when the header line contains the `deload` keyword — the styler hoists it to the session's TOTAL row (see "Session-level flags" below).

## Holds and carries

**A hold time or a carry time is data, not an annotation. It MUST be written to
`duration_min`. Writing it to Notes instead is a bug, not a style choice.**

This applies to every timed, rep-less movement: Dead Hang, Plank, Side Plank,
Hollow Body Hold, L-Sit, Wall Sit, Suitcase Carry, Dumbbell Farmer Walk.

| User input | `reps` | `duration_min` | `distance_km` | Notes |
|---|---|---|---|---|
| `Dead Hang 30s` | 0 | `0:30` | — | (blank) |
| `Plank 45s hold` | 0 | `0:45` | — | (blank) |
| `Side Plank 40s per side` | 0 | `0:40` | — | `per side` |
| `Hollow Body 3x20sec` | 0 | `0:20` × 3 rows | — | (blank) |
| `Suitcase Carry 2x30m @ 24kg` | 0 | — | `0.03` × 2 rows | (blank) |
| `Farmer Walk 40s @ 48kg` | 0 | `0:40` | — | (blank) |

- `duration_min` accepts `MM:SS`, `H:MM:SS`, or decimal minutes. `30s` → `0:30`,
  `1min` → `1:00`, `90 sec` → `1:30`. **Never write `30s` as the literal string
  `30`** — that reads as 30 minutes.
- **Per-set, not per-exercise.** Three 30-second planks are three rows each
  carrying `0:30`, not one row carrying `1:30`.
- **"per side" is qualitative, the number is not.** `40sec per side` → the
  duration goes in `duration_min` and only the words `per side` stay in Notes.
  A side-count is not encodable in the schema, so it belongs in Notes; the time
  never does.
- **No number means no duration.** If the user writes `max hold` or `to
  failure`, leave `duration_min` blank and put the phrase in Notes. Do not
  invent a number, and do not silently drop the row.
- **Carry distance goes in `distance_km`**, converted from metres
  (`30m` → `0.03`). Do not put metres in `duration_min`.

Why this is a hard rule and not a preference: `sessions.py::_is_working_set`
counts a `reps == 0` row as a hard set **only** when `duration_min > 0`. A hold
whose time sits in Notes scores zero sets and zero volume — the work is invisible
to every downstream number. It also breaks the Notes-hygiene convention in
`Skills/CLAUDE.md`: `"30s hold"` repeated across 19 rows is a category, not an
annotation. `shared/canonicalize_logs.py` backfills historical violations and
reports the ones it cannot parse; it is a cleanup path, not a licence to keep
writing them.

## Multi-Set Separator

`///`, `//`, or `/` all mean separate rows.

## Rep × Weight Formats

All equivalent: `8 x 56kg` · `56kg x 8` · `8x56k` · `8 @ 56` · `56 for 8`

Assign the larger number to kg and smaller to reps unless context makes it obvious (e.g. `50 jumping jacks` → 50 reps, 0 kg).

## Name Matching Priority

The output name must ALWAYS be a canonical name from `../../shared/exercises-database.md`, in the exact casing it appears there. Never pass through the user's original casing. Work down this ladder — stop at the first hit:

1. **Exact match** (case-insensitive) → use database casing, no Notes annotation.
2. **Known alias** → check `aliases.md`, use canonical name, no Notes annotation.
   If the alias table's Notes column says to flag ambiguity or names a
   context requirement, honor that before resolving. Example:
   `Abdominal crunch: 30kgx10` can resolve to `Ab Crunch Machine` because
   the load implies a machine; `Abdominal crunch: 20 reps` is bodyweight
   context and should be treated as ambiguous rather than silently mapped
   to the machine.
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

**Distance unit:** the tracker stores distance in km. If the user writes `Swim 550m` or `Run 800m`, convert (`550m` → `0.55`, `800m` → `0.8`). The importer is unit-gated on its side — it reads the `units` field on each quantity and skips a value whose unit isn't the one expected — so imported distances arrive in km. Never log `550` for a 550 m swim; that landed as `550 km` in the historical bug.

**Laps (swim) — no longer manually written.** The old `Laps` column on the monthly CSV was retired in 2026-05. Swim lap counts now live exclusively on `<Person>/data/swimming/YYYY.MM.workouts.csv`, populated by the importer. If the user types `<N> laps` / `<N> lengths` / `<N> Bahnen` on a swim row, the parser may silently ignore it — the value has nowhere to go through `/log`, and the importer derives the canonical count post-hoc on the matching session (distance ÷ pool length).

**Per-workout swim aggregates come from the importer**, not from `/log`: pool length, laps, strokes, SPL, distance and water temperature all land on `swimming/YYYY.MM.workouts.csv`. A manual `/log` swim row records distance + duration only.

**Per-lap swim detail (Stroke / SWOLF / per-lap pace) is permanently unavailable.** It isn't manually parseable and no import path supplies it either — HealthAutoExport exposes no per-lap payload, so no `swimming/*.laps.csv` is written at all (an empty lap file would read as "this swim had no laps", which is worse than an absent one). `Avg SWOLF` and `Stroke Mix` stay blank going forward. Don't tell the user an import will backfill them. Rows written before the migration keep the values they already have — sparse-merge never blanks them.

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

### Coach recovery placeholder line

Coach plans write a single parse-friendly placeholder:

`Recovery: sauna ___ / cold ___ / rlt ___`

Treat a filled `Recovery:` line exactly like modality-specific lines under
the same workout header. Split on `/`, ignore blanks, `___`, `skipped`,
`none`, or `no`, and parse each clause by the modality keyword it starts
with:

- `Recovery: sauna 5min finnish / cold 30s shower / rlt ___`
- `Recovery: sauna 10min 45C infrared / cold shower`
- `Recovery: 5mins Finnish sauna, then cold shower`

The last form is legacy narrative text from the old coach template. It is
still explicit because the line begins with `Recovery:` and contains
`sauna` / `cold`. Normalize it before payload construction:

- `5mins Finnish sauna` -> `heat_type=dry`, `heat_round_durations_min=[5]`
- `10 minutes 45 degrees sauna` -> `heat_type=dry`, `heat_temp_c=45`,
  `heat_round_durations_min=[10]`
- `then cold shower` -> `cold_type=cold_shower`, `cold_duration_sec=null`

When the cold duration is not stated, leave `cold_duration_sec` null; do
not invent 30 seconds or another default. Pair sauna + cold from one
`Recovery:` line into one thermal row.

### Sauna line

`sauna <duration>[+<duration>...]min [<temp>C] [<type>]`

| Form | Writes |
|---|---|
| `sauna 12min` | one round; temp auto-fills from type default (dry → 90°C) |
| `sauna 12min finnish` | named-alias for `dry`; temp falls through to dry default 90°C |
| `sauna 12min 95C dry` | explicit temp + type (user input always wins) |
| `sauna 12+8min` | two rounds (12 + 8 minutes), one row with `heat_round_durations_min: [12, 8]` |
| `sauna 12+8+5min` | three rounds |
| `sauna 10min bio` | Bio-Sauna / Sanarium (~55°C, ~50% humidity) |
| `sauna 8min IR` | infrared cabin (~45°C ambient; heat is radiant) |

- **Plus-shorthand for multi-round saunas.** `12+8min` means two rounds: 12 minutes + 8 minutes. The schema stores per-round durations on one row (NOT one row per round). The total is auto-derived.
- **Heat-type aliases (case-insensitive):**

  | Alias | Resolves to | Default temp (°C) |
  |---|---|---|
  | `finnish` / `dry` | `dry` | 90 |
  | `bio` / `sanarium` | `bio` | 55 (bio-sauna / sanarium range) |
  | `steam` / `dampfbad` | `steam` | 45 (Dampfbad, warm-damp) |
  | `infrared` / `IR` / `infrarot` | `infrared` | 45 (radiant heat, low ambient) |
  | `banya` / `russian` | `banya` | 70 (löyly, humid) |

  Anything else falls through to `dry`. `aufguss` is NOT a type — it's a ritual within a Finnish sauna; if it matters, write `"aufguss"` in Notes (a legitimate user annotation).
- **Temperature:** integer Celsius, suffixed `C` (e.g. `90C`). **Optional** — if omitted, the upsert auto-fills the type default from the table above. Defaults are broad facility norms; the user can always override per-session.

### Cold line

`cold <duration><unit> <type> [<temp>C]`

| Form | Writes |
|---|---|
| `cold 30s shower` | cold_shower, 30 seconds |
| `cold 5min air` | cold_air, 5 minutes (= 300 seconds), temp null — logger will ask once |
| `cold 5min outside -2C` | cold_air with ambient temp −2°C (winter dose) |
| `cold 5min outside 22C` | cold_air with ambient temp 22°C (habit, weak dose) |
| `cold 90s plunge 8C` | cold_plunge with water temp |
| `cold 12min water 14C` | open-water swim / lake / sea |

- **Cold types (case-insensitive aliases):**
  - `air` / `outside` / `outdoor` → `cold_air`
  - `shower` → `cold_shower`
  - `plunge` / `bath` / `ice` → `cold_plunge`
  - `water` / `lake` / `sea` / `swim` → `cold_water`
- **Duration unit:** `s` / `sec` / `seconds` stays in seconds (typical for showers); `m` / `min` / `minutes` converts to seconds (×60). The store column is `cold_duration_sec`.
- **Temperature:** Celsius, optional, signed (`-2`, `0`, `12.5`). Ambient air temp for `cold_air`; water temp for `cold_shower` / `cold_plunge` / `cold_water`.
- **Outdoor temp matters.** A `cold_air` session at −5°C is a fundamentally different stimulus than one at 25°C — they're not the same dose. Always include the temperature on outdoor cold lines when you know it. **If a `cold_air` line is logged without a temperature, the logger asks once before writing** (`SKILL.md` § "Sauna + cold exposure"). Answer with a number in °C or `skip`. The reason this one prompt survives is narrower than "the export has no temperature" — HealthAutoExport does carry ambient `temperature` and `humidity` on workouts, in clean °C. It's that **a standalone sauna or cold-air session is not a workout**: no workout record exists for it, so no imported ambient temperature attaches to it, and the datum can only come from you.

### Pairing rule

A `sauna` line and a `cold` line under the same workout's header within one `/log` message become **one row** in `thermal/YYYY.MM.sessions.csv` — they're assumed to be one protocol session (sauna → cold).

Force separate rows by placing them under different workout headers (e.g. a morning standalone cold shower + an evening post-workout sauna+cold = two rows for that date).

The store dedupes by `(date, start, heat_type, cold_type)`. If `start`
is absent, same-day entries with different heat/cold types can coexist;
same-day entries with the same blank-start protocol shape intentionally
merge. When the user logs two same-type thermal sessions on one date,
include a start time.

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

Omit any field the user didn't provide — sparse-merge applies. `heat_rounds` and `heat_total_min` are auto-derived from `heat_round_durations_min` inside `upsert_thermal_sessions` (don't bother computing them client-side). `heat_temp_c` is auto-filled from the type default (e.g. `dry` → 90°C) when the user didn't supply it.

**Notes hygiene — never echo typed data.** Default `notes` to `null`. Only set `notes` when the user wrote a genuine annotation the schema can't encode (e.g. `sauna 10min 85C dry; felt overheated` → `"felt overheated"`; `sauna 5min finnish aufguss session` → `"aufguss session"`). **Don't reconstruct a description from the typed fields.** Writing `"Finnish sauna; cold exposure by sitting outside"` when `heat_type=dry` and `cold_type=cold_air` already capture that is pure boilerplate — invisible to filtering, clutters the column for real annotations, and forces the user to maintain the same fact in two places. If the structured fields already say it, leave Notes blank.

### Date attachment

For multi-date logs, attach the thermal entry to the date on whose header line the sauna / cold line appears. If the user wrote it on the top-level `/log` header, attach to every date in the message (rare; typically one heat session per workout day).

Never invent sauna or cold sessions. Never prompt for missing data. If the user didn't type a sauna / cold line, they didn't do one — no row.

## Light therapy (opt-in)

If (and only if) the `/log` message contains an explicit light-therapy line, parse it into a `light_therapy` entry keyed to that session's date. All forms case-insensitive. **Absent ≡ didn't happen** — if no light-therapy line appears, omit `light_therapy` from the payload entirely. **Never prompt.**

This module is broad on purpose: it covers red-light therapy (RLT) cabins, near-IR probes, blue-light SAD lamps, and any future photobiomodulation modality. Pick the keyword that matches what the user wrote — the keyword sets the `light_type` default.

### Keywords (case-insensitive)

| Keyword(s) | Default `light_type` |
|---|---|
| `rlt`, `red light`, `redlight` | `red+ir` |
| `near-ir`, `near ir`, `infrared light`, `nir` | `near_ir` |
| `blue light`, `bluelight` | `blue` |
| `light therapy`, `pbm`, `photobiomodulation` | *(leave null; user must specify `light_type`)* |

### Syntax

`<keyword> <duration>min [<wavelength>nm] [<temp>C] [<light_type>] [<body_area>] [<modality>]`

| Form | Writes |
|---|---|
| `rlt 5min` | duration=5; `light_type=red+ir` |
| `rlt 5min 45C` | duration=5, ambient_temp_c=45; `light_type=red+ir`, modality auto-defaults to `cabin` (heated walk-in) |
| `rlt 10min 660nm panel face` | duration=10, wavelength_nm=660, modality=panel, body_area=face |
| `red light 15min full_body` | duration=15, body_area=full_body, `light_type=red+ir` |
| `blue light 30min SAD` | duration=30, `light_type=blue`, notes=`"SAD"` (or leave blank — see Notes hygiene) |
| `near-ir 12min 850nm localized device` | duration=12, wavelength_nm=850, `light_type=near_ir`, body_area=localized, modality=device |
| `pbm 8min red 660nm` | duration=8, `light_type=red`, wavelength_nm=660 |

- **Duration**: integer or decimal minutes. Required.
- **Wavelength**: integer nanometers (e.g. `660`, `850`). Optional.
- **Ambient temp**: integer Celsius, suffix `C`. Optional. Captures heated RLT cabins. When set at/above 30°C and the user didn't specify a modality, the upsert defaults `modality=cabin`.
- **Light type aliases (case-insensitive)**:

  | Alias | Resolves to |
  |---|---|
  | `red`, `red light` | `red` |
  | `nir`, `near-ir`, `near_ir` | `near_ir` |
  | `red+ir`, `red+nir`, `combo` | `red+ir` |
  | `far_ir`, `far-ir`, `fir` | `far_ir` |
  | `blue` | `blue` |
  | `green` | `green` |
  | `white` | `white` |

  Anything else falls through to `other`.
- **Body area aliases (case-insensitive)**:

  | Alias | Resolves to |
  |---|---|
  | `full`, `full_body`, `full body`, `whole body` | `full_body` |
  | `face` | `face` |
  | `back` | `back` |
  | `torso`, `chest` | `torso` |
  | `arm`, `arms` | `arms` |
  | `leg`, `legs` | `legs` |
  | `head` | `head` |
  | `localized`, `local`, `spot` | `localized` |

- **Modality aliases (case-insensitive)**:

  | Alias | Resolves to |
  |---|---|
  | `panel`, `pad` | `panel` |
  | `mask` | `mask` |
  | `wand`, `torch` | `wand` |
  | `cabin`, `booth`, `room` | `cabin` |
  | `device`, `unit` | `device` |
  | `sauna_integrated`, `sauna-integrated`, `in sauna` | `sauna_integrated` |

### Payload entry shape (one row → one entry)

```json
{
  "date": "2026-05-14",
  "start": null,
  "duration_min": 5,
  "light_type": "red+ir",
  "wavelength_nm": null,
  "body_area": "full_body",
  "modality": "cabin",
  "ambient_temp_c": 45,
  "notes": null
}
```

Omit any field the user didn't provide — sparse-merge applies. `modality` is auto-filled to `cabin` inside `upsert_light_therapy_sessions` when `ambient_temp_c >= 30` and the user didn't supply a modality.

### Pairing with thermal — none

Light therapy is **independent** of the sauna/cold pairing rule. A `/log` session that includes both `sauna` and `rlt` lines emits **two payload entries** — one in `thermal`, one in `light_therapy` — both keyed to the same date. They land in two stores. No nullable bloat on either schema; same-session feel preserved by the shared date.

If the user actually used a sauna-integrated red-light panel (some commercial saunas have one), set `modality: "sauna_integrated"` on the light-therapy entry and keep the heat session in the thermal entry as usual.

### Notes hygiene

Same rule as thermal: default `notes` to `null`. Only set when the user typed a genuine annotation the schema can't encode (e.g. `rlt 5min felt warm` → `"felt warm"`). **Don't reconstruct typed fields in Notes.** Writing `"red light therapy 5min at 45C"` when `light_type=red+ir`, `duration_min=5`, `ambient_temp_c=45` already capture it is pure boilerplate — invisible to filtering, clutters the column for real annotations.

### Date attachment

For multi-date logs, attach the light-therapy entry to the date on whose header line the line appears. If on the top-level `/log` header, attach to every date in the message (rare).

Never invent light-therapy sessions. Never prompt for missing data.
