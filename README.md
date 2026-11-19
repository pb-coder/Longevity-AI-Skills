# Workout Tracker

A local-first set of skills for logging workouts, planning a week of strength training, and reviewing progress. Training records and generated plans stay in a private workspace alongside the code checkout.

## What it does

- **Log the training you did.** Record sets, reps, loads, gym or machine context, and optional bodyweight or nutrition-phase entries.
- **Plan the week you intend to train.** Use your goals, available days, established lifts, and exercise preferences to build one full prescription per session.
- **Bring health data in when it suits you.** Import Apple Health data from Health Export Kit in batches. The coach tracks observation dates and import coverage separately, and uses wearable trends as context.
- **Review progress over time.** Follow comparable lift performance and declared cut, maintain, gain, or recomp phases. The coach can defer a change when the evidence is sparse.

The weekly plan is saved as versioned JSON with a gym-friendly Markdown view. A session adjustment can be discussed separately. The log records what actually happened.

## Get started

The CLI uses Python 3 and Git. Put this checkout inside a private tracker workspace, or set `WORKOUT_TRACKER_ROOT` to point to one. See the [workflow guide](docs/WORKFLOW.md) for the data layout, import commands, and optional coaching profile.

From a workspace with the checkout named `Skills`:

```sh
python3 Skills/workout-coach/scripts/read_tracker.py --person "<Person>" --weekly
```

This reads the weekly coaching snapshot. The [workout coach skill](workout-coach/SKILL.md) defines how to turn that snapshot into a validated plan.

| Skill | Use it for |
| --- | --- |
| [Workout coach](workout-coach/SKILL.md) | Weekly plans and training or nutrition reviews |
| [Workout logger](workout-logger/SKILL.md) | Logging completed workouts and managing optional measurements and phases |
| [Longevity optimizer](longevity-optimizer/SKILL.md) | Researching longevity topics with relevant private context |

## Development

Run the tests from the checkout:

```sh
python3 -m unittest discover -s tests
```

See the [coach code map](workout-coach/CODE_MAP.md) and [engineering conventions](CLAUDE.md) for module ownership and data boundaries.
