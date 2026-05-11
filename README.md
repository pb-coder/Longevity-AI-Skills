# Skills

A personal stack of [Claude Code](https://claude.com/claude-code) skills that
together act as a digital twin: log every workout, ingest Apple Health, coach
the next session against training-science evidence, and reason about
longevity interventions with citations. Built for two real users (Nihad +
Fabian) running different data sources side-by-side.

The interesting bit isn't any one skill — it's that they share a CSV-backed
data store under `<Person>/data/` so the coach knows about your blood work,
the longevity advisor knows about your training load, and `/log` is the single
write path. No databases, no servers, no UI. The skills are markdown specs
the LLM reads at runtime; the Python under `shared/` and per-skill `scripts/`
does the actual data work.

## What's in here

| Skill | Trigger | Job |
|---|---|---|
| **workout-logger** | `/log` | Parse a natural-language workout, append to the per-month CSV, sparse-merge bodyweight into `health_metrics.csv`, prompt for Apple Health refresh. Dispatches a research sub-agent when an exercise isn't in the catalog. |
| **workout-coach** | `/coach` | Read the tracker, compute TRIMP / CTL / ATL / TSB / e1RM / HR zones / recovery score, write a training report and the next N workouts to `workout_plan - <Person>.md`. |
| **workout-tracker-maintenance** | `/maintain` | Canonicalize every monthly CSV (idempotent), validate schemas + sort order, optional historical bug-fix sweeps. |
| **longevity-optimizer** | `/longevity` | Sparring partner on supplements, biomarkers, dermatology, circadian, interventions. Cites peer-reviewed sources. Loads personal data from `<Person>/data/longevity/*.md` — never inlines PII into the skill repo. |

## Why this exists

Most fitness apps are a black box. This one is the opposite: every CSV is
human-readable, every decision the coach makes is traceable to a JSON field
in `read_tracker.py` and a numbered section of `references/training-science.md`,
and every longevity recommendation cites the study it came from. The user
owns the data, locally, in plain text.

A few load-bearing design calls:

- **Markdown is truth.** The exercises catalog, the alias table, the coach
  rubric, the longevity framework — all markdown. The LLM reads them at
  runtime. Adding an exercise or alias is a one-line PR; no migration.
- **CSV is the canonical store.** No xlsx, no DB. `canonicalize_monthly_csv`
  is idempotent and self-heals out-of-order rows on the next pass.
- **Two-source parity.** Nihad's tracker reads Apple Health's native XML
  export (rich: HRV, wrist temp, sleep stages, per-workout HR). Fabian's
  reads HLExport's text dump (slimmer). The coach gates report sections on
  a `capabilities` dict so HL users never see "not enough HRV data yet"
  prompts for metrics their source can't provide.
- **Recovery as a personal z-score.** No population norms. Each driver
  (HRV, RHR, sleep, wrist temp, HR Recovery, sleep consistency) z-scores
  against the user's own rolling baseline. 5/10 means "average for this
  user," not "average for adult males." HL users with fewer signals aren't
  structurally biased downward — weights renormalize over what's present.
- **e1RM that respects context.** When Nihad changes gyms and a cable
  ratio recalibrates his lateral-raise dial, the slope regression sees
  through the discontinuity — user-tagged context-change rows are
  excluded from the trend math and confidence drops one band.
- **Apple Health quirks have callouts in code.** Unit-aware distance
  (Swim sums arrive in metres), GymKit dedupe (machine workouts win over
  Watch-estimated duplicates), per-lap swim event parsing for SPL / SWOLF.

## Layout

```
Skills/
├── shared/                            # Python the skills share
│   ├── person_paths.py                # path resolver (data_dir, monthly_csv, swim_*, ...)
│   ├── csv_store.py                   # health_metrics / workout_sessions / swim CSVs
│   ├── monthly_csv.py                 # per-month workout CSV reader / writer / canonicalizer
│   ├── exercises_database.py          # parse + lookup + fuzzy + propose; atomic + validating
│   ├── exercises-database.md          # canonical exercise catalog (markdown is truth)
│   ├── import_apple_health.py         # Apple Health XML → CSV
│   ├── import_hl_export.py            # HLExport text dump → CSV
│   └── apple_workout_types.py         # Apple HKWorkoutActivityType enum + mapping
├── workout-logger/                    # /log
├── workout-coach/                     # /coach
├── workout-tracker-maintenance/       # /maintain
├── longevity-optimizer/               # /longevity
├── CLAUDE.md                          # the contributor / future-me doc
└── PROJECT.md                         # sheet format + routing rules + backup
```

Each per-person data folder lives **one directory up** from this repo:

```
<Person>/data/
├── health_metrics.csv      # Apple Health daily aggregates (HRV, RHR, sleep, wrist temp, ...)
├── workout_sessions.csv    # one row per Apple workout
├── profile.csv             # key/value: source, auto_cardio, birthday, swim CSS, ...
├── monthly/YYYY.MM.csv     # one CSV per month — strength + cardio sets
├── swimming/               # XML-only
│   ├── YYYY.MM.workouts.csv
│   └── YYYY.MM.laps.csv
└── longevity/              # /longevity personal data — outside the Skills repo by design
    ├── profile.md
    ├── state.md
    ├── interventions.md
    └── biomarkers.md
```

## Using it

Install [Claude Code](https://claude.com/claude-code), clone this repo into
your skills directory, and the slash commands light up. There's no install
step beyond that — the skills are markdown, the Python helpers are stdlib
only.

Each skill's `SKILL.md` is the spec the LLM follows. Read those if you want
to see how a skill actually works; they're not auto-generated.

## What's a skill?

A markdown file with YAML frontmatter (`name`, `description`) that tells
Claude when to activate and what to do. See
[the Skills docs](https://docs.claude.com/en/docs/agents-and-tools/agent-skills).
Each skill in this repo is one of those plus a `scripts/` directory for
Python helpers and a `references/` directory for additional context the LLM
loads on demand.

## Status

In active personal use. Not packaged, not pip-installable, not stable enough
to recommend cloning unmodified. Read the code; lift the parts that look
useful. The training-science reference, the recovery-score architecture, and
the e1RM-with-context-aware-slope are the bits most worth borrowing.

Personal data stays out of this repo — `<Person>/data/` is intentionally
*above* the Skills directory so a `git clone` never picks it up.
