# Skills

Claude Code skills for workout logging, training analysis, and longevity research. Personal use.

## Skills

- `workout-logger` (`/log`): parses a free-form workout into the per-month CSV store. When an exercise isn't in the catalog, dispatches a research sub-agent to propose an addition. The user confirms before write.
- `workout-coach` (`/coach`): reads the tracker, computes training load (TRIMP, CTL/ATL/TSB), e1RM trajectories, HR zones, recovery score. Writes a report and the next N workouts to a plan file.
- `longevity-optimizer` (`/longevity`): supplement, biomarker, dermatology, and circadian queries. Reads personal data from a directory outside the repo. Cites peer-reviewed sources before claims.

A maintenance utility lives at `shared/maintain.py`. Run it directly when you need to sweep canonicalize across all months (after a schema change or manual edit to a past month) or validate the CSV store: `python3 Skills/shared/maintain.py --person <Name>`.

## Architecture

The Git repo root is `Skills/`. Per-person data (`../<Person>`) and
generated plans (`../plans`) are never committed to it. Each person's
`../<Person>/data/` is a separate repository of its own — see below.

Public CLIs remain stable and thin: they parse arguments, resolve a
person, call domain code, and print status or JSON. Shared primitives
that should not be copied between skills live in `tracker/`: CSV table
mechanics, command context, typed contracts, and benchmark helpers.
Skill-specific behavior stays in `shared/`, `workout-logger/`, and
`workout-coach/`. Python imports are package-based: shared helpers live
under `shared.*`, tracker primitives under `tracker.*`, and coach
internals under `workout_coach.lib.*`. The underscore package is an
import facade for the historical `workout-coach/` skill directory, whose
public script paths remain unchanged.

CSV storage is split by responsibility: `shared/csv_store.py` is the
backward-compatible import facade, `csv_store_profile.py` owns profile
keys, `csv_store_dense.py` owns health metrics and workout sessions,
`csv_store_periodic.py` owns swim/sleep/thermal/light/nutrition stores,
and `csv_store_common.py` owns shared table helpers.

Monthly workout CSV logic follows the same pattern: `shared/monthly_csv.py`
is the compatibility facade, with schema constants, value coercion,
file I/O, canonicalization, and upserts split across
`monthly_csv_schema.py`, `monthly_csv_values.py`, `monthly_csv_io.py`,
`monthly_csv_canonicalize.py`, and `monthly_csv_upsert.py`.

There is one importer: `shared/import_health_auto_export.py`, which
reads `HealthAutoExport*.zip`. It dispatches on archive member — a
`HealthAutoExport-*.json` member selects the JSON reader; anything else
falls back to the deprecated CSV reader. JSON is the only supported
format going forward, because it names metrics in canonical English
regardless of phone locale and carries the per-night sleep timestamps
the Sleep Regularity Index needs. Source-agnostic helpers live beside
it: `shared/health_units.py` (unit conversion tables, plausibility
ranges, timestamp parsing) and `shared/strength_sessions.py`
(strength-session clustering). `shared/apple_workout_types.py` keeps
its name because it genuinely models Apple's activity-type enum.

Each person's `data/` directory is its own git repository.
`shared/data_git.py::commit_data(person, message)` commits it after
every confirmed write — one operation, one commit — from both
`workout-logger/scripts/append_workout.py` and the importer. It never
raises into the caller: losing the history of a write is an annoyance,
losing the write is not acceptable.

Code quality rules for this repo:

- Preserve command names, CSV schemas, file locations, and generated
  output semantics unless a change is explicitly documented.
- Keep one source of truth per concept: path rules, schemas, CSV I/O,
  date parsing, exercise catalog loading, and capability gating.
- Keep disk I/O in store modules; keep analytics functions pure where
  practical.
- Measure performance changes with reproducible commands before adding
  caching or complexity.
- Do not commit real person names, relationships, locations, ages,
  medication details, lab status, or other profile facts in docs. Use
  `<Person>` / `<OtherPerson>` placeholders and load private context
  from the uncommitted per-person data folders at runtime.

## Data store

CSV under `<Person>/data/`, sibling to the skill repo:

```
<Person>/data/
├── health_metrics.csv          # daily health rollup, 22 columns
├── workout_sessions.csv        # one row per Apple workout
├── profile.csv                 # key/value config
├── monthly/YYYY.MM.csv         # per-month strength + cardio log
├── swimming/
│   ├── YYYY.MM.workouts.csv    # per-workout aggregates
│   └── YYYY.MM.laps.csv        # XML-era rows only; no importer writes laps now
├── sleep/                      # importer or manual /log entries
│   └── YYYY.MM.nights.csv      # per-night architecture (6 stages + InBed + Efficiency + clock times; N Segments blank)
├── thermal/                    # manual /log only (sauna + cold exposure)
│   └── YYYY.MM.sessions.csv    # per-session heat (type/temp/rounds/durations/total) + cold (type/duration/temp)
└── longevity/                  # personal data; never committed
    ├── profile.md
    ├── state.md
    ├── interventions.md
    └── biomarkers.md
```

The data folder sits above the Skills directory so a clone of the repo never picks it up.

## Design notes

The exercise catalog, alias table, training-science reference, and longevity framework are markdown. The LLM reads them at runtime. Adding an entry is a one-line edit; no migration step.

`canonicalize_monthly_csv` is idempotent. Out-of-order rows and stale schema columns self-heal on the next pass.

HealthAutoExport JSON populates the full health/sleep/workout schema the coach reads, including the per-night bedtime and wake timestamps the Sleep Regularity Index runs on. Two things it does not expose: per-lap swim detail and sleep segment counts, so swim SWOLF / stroke mix and sleep fragmentation degrade to null rather than to zero. The coach still gates report sections on a `capabilities` dict, so a partially populated tracker doesn't see prompts for metrics its data can't support.

Recovery is a personal z-score against the user's own rolling baseline. 5/10 means average for this person. Weights renormalize over signals that are actually present.

e1RM regression skips user-tagged context-change rows (gym swap, cable ratio recalibration) so a gym change doesn't read as a strength regression.

## Status

In active personal use. The current test baseline is
`python3 -m unittest discover -s tests -v`. Treat local benchmark
numbers as sanity checks, not hard performance targets.
