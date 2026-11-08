# Longevity AI Skills

Personal skills for workout logging, training analysis, and longevity research.

- `workout-logger` (`/log`) parses workouts into monthly CSVs, with optional bodyweight, sleep, swim CSS tests, and nutrition-phase updates. Unknown exercises follow a user-confirmed catalog proposal flow.
- `workout-coach` (`/coach`) analyzes training, recovery, strength progression, swimming, and nutrition context. It writes dated assessment JSON and strength-workout markdown, then validates both.
- `longevity-optimizer` (`/longevity`) researches interventions and biomarkers using private context and cited evidence.

Read each skill's `SKILL.md` for its workflow. Developer conventions live in [CLAUDE.md](CLAUDE.md); coach module ownership is in [workout-coach/CODE_MAP.md](workout-coach/CODE_MAP.md).

## Storage and outputs

The repository root is `Skills/`. Private data and generated plans live beside it and are never committed here:

```
<root>/
├── <Person>/data/
│   ├── health_metrics.csv
│   ├── workout_sessions.csv
│   ├── profile.csv
│   ├── monthly/YYYY.MM.csv
│   ├── swimming/YYYY.MM.workouts.csv
│   ├── sleep/YYYY.MM.nights.csv
│   ├── nutrition_phases.csv        # phase records when configured
│   └── longevity/                 # private profile, state, interventions, biomarkers
├── plans/<Person>/
│   ├── YYYY-MM-DD-coach_reads.json
│   └── YYYY-MM-DD-workout.md
└── Skills/
```

Each person's `data/` is its own git repository, committed once per confirmed write. Git history provides rollback. History failures warn without failing the write; automatic repacking is prohibited for synced folders. Existing historical swim lap CSVs remain readable but receive no new writes.

`shared/import_health_export_kit.py` is the only importer. It reads `health-export-json-*.json`, updates supported health, workout, sleep, and swim fields, and archives the consumed export after success (`--keep-export` leaves the source in place). When more than one export is present, an explicit path is required. It does not supply daily HRV, wrist temperature, or per-lap swim detail; unavailable signals are omitted rather than treated as zero or requested from the user.

## Monthly CSV schema migration

Schema v2 appends three optional columns, `Gym`, `Machine`, and `Load Basis`, after the unchanged 18-column schema. Readers accept legacy 17- and 18-column rows and treat missing context as unknown. A touched month is rewritten atomically in v2 on its next successful update or maintenance pass; there is no automatic bulk migration or invented historical metadata. Back up data and keep its history before an explicit maintenance migration. Rollback to software predating v2 requires restoring a pre-migration backup: old writers can drop new fields.

For each set, `gym` and `machine` are explicit labels; `load_basis` is `total` or `plates_only`. Blank means unknown and retains legacy interpretation. Partial-bar figures are never used as total load for progression or e1RM. When named machine contexts exist, only a fully specified matching gym and machine are comparable; mixed or incomplete contexts cannot progress automatically. Replays with changed metadata are conflicts unless explicitly corrected.

## Paired import workflow

`python3 shared/prepare_training.py --entry <Person> <export.json> <workout-payload.json>` previews a named pairing. Repeat `--entry` for multiple people; use `-` for an omitted input. Review the pairings and add `--apply` to log workouts and import the corresponding health exports. Each export path must be unique, and the caller supplies ownership because the export cannot prove it. All entries are preflighted before writes; if an application step fails, earlier completed writes are not rolled back. `--allow-past-months` is available when needed.

## Architecture and maintenance

- `tracker/`: shared command context, typed contracts, CSV mechanics.
- `shared/`: person-relative paths, stores, canonicalization, exercise catalog, importer, data history.
- Skill directories: entry instructions, references, public scripts, and domain analytics.
- `workout_coach/`: Python import facade for `workout-coach/`.

CSV store and monthly-log facades delegate to focused schema, I/O, and policy modules. Keep one source of truth for paths, schemas, dates, catalog parsing, and capability gates. Preserve public contracts unless an intentional migration is documented. Notes are for row-specific user annotations.

From this repository, run `python3 -m unittest discover -s tests -v`. From the tracker root, run `python3 Skills/shared/maintain.py --person <Person>` to canonicalize all months and validate stores after migrations or manual edits.

Committed text must use `<Person>` / `<OtherPerson>` placeholders, never private profile facts. Private context stays outside this repository.

## Retired features

HTML dashboards and `render_dashboard.py` are retired; there is no HTML output or report-rendering command. Use the saved assessment JSON and workout markdown. The former HTML-only options and `Assessment:` links are unsupported.

Thermal (sauna/cold) and light-therapy tracking, adherence analytics, suggestion inputs, and plan placeholders are retired. `thermal` and `light_therapy` logger payload keys are unsupported. Existing private CSVs and old generated reports are left untouched; they are not current coaching inputs. General longevity research remains available without claims of live modality tracking.

The unused coach JSON outputs `tier_history`, `bodyweight_weekly`, and `week_over_week` are retired. Use the current session recommendation, bodyweight trend, and existing aggregate inputs. The unused public swim-lap writer `upsert_swim_laps` is retired; historical lap readers remain supported and imported swim aggregates continue unchanged.

Importer status combines daily and sleep updates into one `Health Metrics:` line; its written/updated counts aggregate both passes.
