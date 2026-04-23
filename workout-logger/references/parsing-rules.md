# Parsing Rules

## Date

`DD.MM` → `YYYY-MM-DD` using current year. If omitted, ask once.

## Fields

- **#**: One number per exercise. All sets of the same exercise share the number.
- **Set**: 1, 2, 3... per exercise
- **kg**: 0 if no weight. `k` = `kg`. `lbs` or `lb` → divide by 2.205, round to nearest 0.5.
- **Volume**: Reps × kg
- **Reps**: 0 for carries, walks, holds, isometric positions. Put the duration in the `duration_min` field (accepts `MM:SS` or decimal minutes) so the coach can read it structurally. Put distance in `distance_km` when the exercise tracks distance (farmer walks, loaded carries). Use Notes only for qualitative detail like "per hand" or "beltless".
- **Notes**: Only from parenthetical input like `(felt heavy)`. Never invent notes. Exception: `Deload Workout` on the first row of a session when the header line contains the `deload` keyword (see "Session-level flags" below).

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

If the word `deload` appears anywhere on the `/log` header line (before the first exercise bullet), set the first row of that session's `notes` to `Deload Workout`. The coach reads this marker to drive mesocycle analysis — it's the one piece of Notes the coach actually parses.

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

## Bodyweight (opt-in)

If (and only if) the `/log` message contains an explicit bodyweight line, parse it into a `bodyweight` entry keyed to the session's date. Accepted forms (case-insensitive):

- `weight 76.5`, `weight: 76.5`, `weight 76.5 kg`
- `bw 76.5`, `bw: 76.5kg`
- `bodyweight 76.5`, `bodyweight: 76.5`

Default `notes` to `null`. Only set `notes` when the user gave an explicit non-morning context on the same line (e.g. `weight 77.1 after dinner` → `"evening, not fasted"`). The standing convention is **morning, empty stomach**, so a bare number needs no note.

For multi-date logs, attach the weight to the date on whose header line it appears. If the user wrote the weight on the top-level `/log` header, attach it to every date in the message.

Never invent or guess a weight. If no bodyweight line is present, omit `bodyweight` from the payload entirely.
