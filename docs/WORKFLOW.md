# Working with Workout Tracker

## Workspace layout

Keep the code checkout inside a tracker workspace. The default data root is the parent of the checkout. Set `WORKOUT_TRACKER_ROOT` to use a different private workspace.

```text
Workout Tracker/
├── Skills/                        # this Git checkout
├── <Person>/data/
│   ├── profile.csv
│   ├── coach_profile.json          # optional coaching preferences
│   ├── monthly/YYYY.MM.csv
│   ├── health_metrics.csv
│   ├── health_imports.csv         # optional applied import receipts
│   ├── workout_sessions.csv
│   ├── sleep/
│   ├── swimming/
│   └── nutrition_phases.csv
├── plans/<Person>/
│   ├── weekly/                    # versioned prescription JSON and workout Markdown
│   ├── block-YYYY-MM-DD.json
│   └── YYYY-MM-DD-workout.md       # historical format, when present
└── archive/health-exports/
```

Each person's data directory has its own local Git history. Keep those histories and generated plans private. The source checkout should contain synthetic examples and fixtures only. Run the privacy check in [CLAUDE.md](../CLAUDE.md) before any push.

## Coaching a week

From the workspace root, read a private snapshot:

```sh
python3 Skills/workout-coach/scripts/read_tracker.py --person "<Person>" --weekly --months 6
```

By default, a weekend review plans for the upcoming Monday. A weekday review reuses the current published week when there is one. Otherwise it chooses a new seven-day period. Set `--week-start` explicitly when planning further ahead. Use `--sessions`, `--training-days` or `--minutes` to represent this week's real availability. Dated revisions can supply just the remaining training days. The snapshot keeps earlier dated slots and reports the required total.

The [coach instructions](../workout-coach/SKILL.md) define the structured draft. `publish_week.py` verifies the draft against a weekly snapshot, writes one revision under `plans/<Person>/weekly/`, and returns both output paths. The versioned JSON is the training prescription and the Markdown is the gym-facing view. The workout lists the full intended sessions and their doses. Session adjustments can be discussed separately when requested. The tracker still reads historical Markdown, and `check_plan.py` remains available for historical assessments and plans. The dated diagnostic from `read_tracker.py` without `--weekly` retains its legacy daily gate.

Log what you actually did. Adherence matches logged sets to prescriptions from the relevant period. It uses scheduled dates and exercise overlap when possible. Flexible dates or incomplete logs can leave attribution uncertain. Earlier dated prescriptions remain in their original revision when the rest of the week changes. When you actively start a new training block, persist it with `PYTHONPATH=Skills python3 -m workout_coach.lib.blocks write --person "<Person>" --from-week YYYY-MM-DD`.

## Optional coaching profile

Use the default history or explicitly save a profile in the private tracker. This example declares an exercise-specific goal, a secondary goal and a location-specific equipment restriction.

```json
{
  "goals": [
    {"type": "strength", "exercise": "Flat Barbell Bench Press"},
    {"type": "swim"}
  ],
  "default_gym": "Training gym",
  "preferences": [{"exercise": "Flat Barbell Bench Press"}],
  "restrictions": [
    {
      "exercise": "Chest Press Machine",
      "type": "unavailable",
      "location": "Travel gym"
    }
  ]
}
```

```sh
python3 Skills/workout-coach/scripts/coach_profile.py --person "<Person>" /path/to/private-profile.json
```

Goal types are `strength`, `muscle_growth`, `cardio`, `swim` and `general`. A strength goal names the relevant lift. Restrictions support `avoid`, `limitation` and `unavailable`, scoped by optional `location`, `variant`, `start_date` and `end_date`. A flexible date, gym or variant must be clarified when it could affect an explicit restriction. A profile can also record `equipment` by location and `observations` with an exercise, type (`effort`, `discomfort` or `preference`), date, and note. The coach can consider exercise history without a profile. An omission can reflect availability, scheduling or choice, so it carries no automatic exclusion.

## Nutrition reviews

Use the [workout logger](../workout-logger/SKILL.md#nutrition-phase-opt-in) to record a cut, bulk, maintain or recomp phase. `target_rate_percent_per_week` is signed. Use `-0.4` to record an agreed target of losing 0.4% per week. The optional positive `reference_weight_kg` fixes the scale used for conversion. Existing `target_rate_kg_per_wk` targets remain readable. New optional columns follow the original eight-column CSV layout and are written when a phase file is updated.

The weekly review uses comparable within-phase measurements and defers when they are sparse, old or ambiguous. It keeps the recorded phase, the goal and the measured trend distinct. Intake and protein targets describe intentions. Device expenditure remains an estimate.

## Health imports

Use `shared/import_health_export_kit.py` for Health Export Kit JSON. The importer uses the selected date range and archives the export after a successful import. Use `--keep-export` to retain the source. Pass `--export` when there is more than one candidate. Run with `--dry-run` to inspect the range and conflicts. Use `--overwrite-existing` only after reviewing the populated values that would change. Existing observation fields have limited provenance. An import receipt records the applied range and the import date separately, without establishing that each metric was measured on every date. Earlier exports can have unknown receipt information.

## Monthly CSV schema migration

Schema v2 appends three optional columns, `Gym`, `Machine`, and `Load Basis`, after the unchanged 18-column schema. Readers accept legacy 17- and 18-column rows and treat missing context as unknown. A touched month is rewritten atomically in v2 on its next successful update or maintenance pass; there is no automatic bulk migration or invented historical metadata. Back up data and keep its history before an explicit maintenance migration. Rollback to software predating v2 requires restoring a pre-migration backup: old writers can drop new fields.

For each set, `gym` and `machine` are explicit labels; `load_basis` is `total` or `plates_only`. Blank means unknown and retains legacy interpretation. Partial-bar figures are never used as total load for progression or e1RM. When named machine contexts exist, only a fully specified matching gym and machine are comparable; mixed or incomplete contexts cannot progress automatically. Replays with changed metadata are conflicts unless explicitly corrected.

## Paired import workflow

`python3 shared/prepare_training.py --entry <Person> <export.json> <workout-payload.json>` previews a named pairing. Repeat `--entry` for multiple people; use `-` for an omitted input. Review the pairings and add `--apply` to log workouts and import the corresponding health exports. Each export path must be unique, and the caller supplies ownership because the export cannot prove it. All entries are preflighted before writes; if an application step fails, earlier completed writes are not rolled back. `--allow-past-months` is available when needed.

The preview reports import conflicts for every entry, including conflicts created by manual sleep or bodyweight in the paired payload. Applying requires `--overwrite-existing` if any import has conflicts; this option is passed to each importer.

## Retired features

HTML dashboards and `render_dashboard.py` are retired; there is no HTML output or report-rendering command. Use the saved assessment JSON and workout markdown. The former HTML-only options and `Assessment:` links are unsupported.

Thermal (sauna/cold) and light-therapy tracking, adherence analytics, suggestion inputs, and plan placeholders are retired. `thermal` and `light_therapy` logger payload keys are unsupported. Existing private CSVs and old generated reports are left untouched; they are not current coaching inputs. General longevity research remains available without claims of live modality tracking.

The unused coach JSON outputs `tier_history`, `bodyweight_weekly`, and `week_over_week` are retired. Use the current session recommendation, bodyweight trend, and existing aggregate inputs. The unused public swim-lap writer `upsert_swim_laps` is retired; historical lap readers remain supported and imported swim aggregates continue unchanged.

Importer status combines daily and sleep updates into one `Health Metrics:` line; its written/updated counts aggregate both passes.
