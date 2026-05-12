# Skills

Claude Code skills for workout logging, training analysis, and longevity research. Personal use.

## Skills

- `workout-logger` (`/log`): parses a free-form workout into the per-month CSV store. When an exercise isn't in the catalog, dispatches a research sub-agent to propose an addition. The user confirms before write.
- `workout-coach` (`/coach`): reads the tracker, computes training load (TRIMP, CTL/ATL/TSB), e1RM trajectories, HR zones, recovery score. Writes a report and the next N workouts to a plan file.
- `longevity-optimizer` (`/longevity`): supplement, biomarker, dermatology, and circadian queries. Reads personal data from a directory outside the repo. Cites peer-reviewed sources before claims.

A maintenance utility lives at `shared/maintain.py`. Run it directly when you need to sweep canonicalize across all months (after a schema change or manual edit to a past month) or validate the CSV store: `python3 Skills/shared/maintain.py --person <Name>`.

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

Apple Health and HLExport sources have different feature surfaces. The coach gates report sections on a `capabilities` dict so a tracker on the slimmer source doesn't see "missing HRV data" prompts for metrics that source can't provide.

Recovery is a personal z-score against the user's own rolling baseline. 5/10 means average for this person. Weights renormalize over signals that are actually present.

e1RM regression skips user-tagged context-change rows (gym swap, cable ratio recalibration) so a gym change doesn't read as a strength regression.

## Status

In active personal use. Not packaged. Read the code; lift what's useful.
