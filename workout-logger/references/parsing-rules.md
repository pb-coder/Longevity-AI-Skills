# Parsing Rules

## Date

`DD.MM` → `YYYY-MM-DD` using current year. If omitted, ask once.

## Fields

- **#**: One number per exercise. All sets of the same exercise share the number.
- **Set**: 1, 2, 3... per exercise
- **kg**: 0 if no weight. `k` = `kg`. `lbs` or `lb` → divide by 2.205, round to nearest 0.5.
- **Volume**: Reps × kg
- **Reps**: 0 for carries, walks, holds — put duration/distance in Notes.
- **Notes**: Only from parenthetical input like `(felt heavy)`. Never invent notes.

## Multi-Set Separator

`///`, `//`, or `/` all mean separate rows.

## Rep × Weight Formats

All equivalent: `8 x 56kg` · `56kg x 8` · `8x56k` · `8 @ 56` · `56 for 8`

Assign the larger number to kg and smaller to reps unless context makes it obvious (e.g. `50 jumping jacks` → 50 reps, 0 kg).

## Name Matching Priority

The output name must ALWAYS be a canonical name from `exercises-database.md`, in the exact casing it appears there. Never pass through the user's original casing.

1. **Exact match** (case-insensitive) → use database casing
2. **Known alias** → check `aliases.md`
3. **Substring match** → input contained in canonical name or vice versa; resolve with equipment context
4. **Fuzzy match** → best guess, add Notes: `(matched from: "user's input")`
5. **No match** → user's name in title case, add Notes: `(not in database)`

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
