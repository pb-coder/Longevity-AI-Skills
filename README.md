# Skills

Claude Code skills for workout logging, training analysis, and longevity research. Personal use.

## Skills

- `workout-logger` (`/log`): parses a free-form workout into the per-month CSV store. When an exercise isn't in the catalog, dispatches a research sub-agent to propose an addition. The user confirms before write.
- `workout-coach` (`/coach`): reads the tracker, computes training load (TRIMP, CTL/ATL/TSB), e1RM trajectories, HR zones, recovery score. Writes a report and the next N workouts to a plan file.
- `longevity-optimizer` (`/longevity`): supplement, biomarker, dermatology, and circadian queries. Reads personal data from a directory outside the repo. Cites peer-reviewed sources before claims.

A maintenance utility lives at `shared/maintain.py`. Run it directly when you need to sweep canonicalize across all months (after a schema change or manual edit to a past month) or validate the CSV store: `python3 Skills/shared/maintain.py --person <Name>`.

## Architecture

The Git repo root is `Skills/`. Per-person data (`../<Person>`) and
generated plans (`../plans`) stay outside Git.

Public CLIs remain stable and thin: they parse arguments, resolve a
person, call domain code, and print status or JSON. Shared primitives
that should not be copied between skills live in `tracker/`: CSV table
mechanics, command context, typed contracts, and benchmark helpers.
Skill-specific behavior stays in `shared/`, `workout-logger/`, and
`workout-coach/`.

CSV storage is split by responsibility: `shared/csv_store.py` is the
backward-compatible import facade, `csv_store_profile.py` owns profile
keys, `csv_store_dense.py` owns health metrics and workout sessions,
`csv_store_periodic.py` owns swim/sleep/thermal/light/nutrition stores,
and `csv_store_common.py` owns shared table helpers.

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
├── health_metrics.csv          # daily Apple Health rollup
├── workout_sessions.csv        # one row per Apple workout
├── profile.csv                 # key/value config
├── monthly/YYYY.MM.csv         # per-month strength + cardio log
├── swimming/                   # XML source only
│   ├── YYYY.MM.workouts.csv
│   └── YYYY.MM.laps.csv
├── sleep/                      # XML source only (or manual /log entries)
│   └── YYYY.MM.nights.csv      # per-night architecture (6 stages + InBed + Efficiency + segments + clock times)
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

Apple native XML and HealthAutoExport both populate the full health/sleep/workout schema used by the coach. The coach still gates report sections on a `capabilities` dict so legacy or partially populated trackers don't see prompts for metrics their source can't provide.

Recovery is a personal z-score against the user's own rolling baseline. 5/10 means average for this person. Weights renormalize over signals that are actually present.

e1RM regression skips user-tagged context-change rows (gym swap, cable ratio recalibration) so a gym change doesn't read as a strength regression.

## Status

In active personal use. The current test baseline is
`python3 -m unittest discover -s tests -v`. Treat local benchmark
numbers as sanity checks, not hard performance targets.
