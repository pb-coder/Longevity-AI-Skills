# Skills

Source for the Claude Code skills used by pb-coder. Cloned from
[`pb-coder/Skills`](https://github.com/pb-coder/Skills); edit here and push.

## Layout

```
shared/               # Code + docs imported by multiple skills
  tracker_sheet.py    # Single authority for the per-person tracker xlsx files:
                      #   layout constants (monthly / Bodyweight / DB),
                      #   coercions (date_str, bw_locate_date, _numeric_cell),
                      #   and canonical sheet styling (style_monthly_sheet,
                      #   style_bodyweight_sheet, style_db_sheet). Idempotent.
                      #   style_monthly_sheet auto-sorts sessions by date
                      #   ascending and merges non-contiguous same-date blocks
                      #   on every pass.
  exercises-database.md  # Canonical exercise catalog (muscle → pattern →
                         # exercises). Source of truth — the xlsx "Exercises
                         # Database" tab is mirrored from this via
                         # sync_db_sheet.py. Read by /log (name lookup) and
                         # /coach (muscle mapping + tag reading).
  sync_db_sheet.py    # Mirror exercises-database.md → xlsx "Exercises Database"
                      # tab. Idempotent: missing entries are inserted at the
                      # end of their section, new sections appended at the
                      # bottom with a navy header. Run after editing the
                      # markdown so both tracker xlsx files stay in sync.
                      # Usage: python3 shared/sync_db_sheet.py "<tracker>.xlsx"
  canonicalize_logs.py  # One-shot rename map for past monthly sheets. Fixes
                        # historical typo'd exercise names ("Deadhang" → "Dead
                        # Hang", "Dips" → "Dip", "Stomach Press*" →
                        # "Ab Crunch Machine", etc.) and clears stale
                        # "(not in database)" Notes once the exercise is
                        # canonical. Reports ambiguous names (e.g. bare
                        # "Leg Curl") instead of auto-renaming. Re-runnable.
                        # Usage: python3 shared/canonicalize_logs.py "<tracker>.xlsx"

workout-logger/       # /log — append a parsed workout to the tracker.
  SKILL.md            # Agent entry point.
  scripts/
    append_workout.py # Routes rows to YYYY.MM sheets, upserts bodyweight,
                      # applies the styler. Single writer.
  references/         # aliases.md, parsing-rules.md, common-mistakes.md

workout-coach/        # /coach — read tracker, report, plan next workout.
  SKILL.md
  scripts/
    read_tracker.py   # Emits one JSON blob (progression, volume per muscle,
                      # e1RM, stale/unknown exercises, bodyweight trend,
                      # cardio summary, rows). Null keys are dropped for
                      # token efficiency.
  references/training-science.md

workout-tracker-maintenance/   # /maintain — end-of-month cleanup.
  SKILL.md
  scripts/maintain.py # Restyle, trim, reorder, verify.

longevity-optimizer/  # /longevity — separate domain (not workout-tracker).
```

## Conventions

- **Python scripts** live under `scripts/` per skill and are invoked by the
  agent via Bash.
- **Shared imports**: consumers add `shared/` to `sys.path` via
  `sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))`
  and import from `tracker_sheet`.
- **Styler is canonical**: `style_monthly_sheet` is the single source of
  truth for monthly-sheet layout (column widths, fonts, fills, merges,
  SESSION numbering, TOTAL row placement, chronological row order).
  Running it twice is a no-op. `/log` calls it post-write; `/maintain`
  calls it on every sheet. An out-of-order sheet (e.g. after a backfill)
  self-heals on the next pass.
- **Opt-in bodyweight**: `/log` does **not** prompt for morning weight.
  The user includes a line like `weight 76.5` (or `bw 76.5`, `bodyweight:
  76.5`) in the `/log` message when they want to record one. Bulk seeding
  backfills go through `append_workout.py` with a
  `{"rows": [], "bodyweight": [...]}` payload.
- **Exercise canonicalization**: `shared/exercises-database.md` is the
  single source of truth for canonical exercise names. The `/log` agent
  consults `workout-logger/references/aliases.md` to map plurals,
  synonyms, and old typo'd names (e.g. `Hiking` → `Hike`, `Stomach Press`
  → `Ab Crunch Machine`). The aliases file is read by the agent at
  logging time, not by code, so adding an alias takes effect on the next
  `/log` run. After adding new entries to the markdown, run
  `python3 shared/sync_db_sheet.py "Workout Tracker - <Person>.xlsx"` to
  mirror them into the xlsx "Exercises Database" tab so the user-facing
  catalog reflects the change. Don't add exercises by hand inside the
  xlsx — they'll be silently ignored by `/coach` (which reads only the
  markdown) and overwritten on the next sync.
- **Cardio + wellness logging is supported**: the markdown now includes a
  CARDIO section (Hike, Swim, Walk, Outdoor Run, Outdoor Cycling +
  indoor machines) and a WELLNESS section (Yoga, Stretching). These
  entries have no muscle tags, so they're logged and counted toward
  `cardio_last_14d` (where applicable) without contributing to the
  weekly hard-set volume model.
- **Coach plan output includes a per-workout DATE placeholder**: every
  strength workout heading is followed by `**Date:** ___________` on its
  own line so the user can fill in the date when they actually train and
  not lose track when `/log`-ing later.

## Workout Tracker

The tracker xlsx files (`Workout Tracker - <Person>.xlsx`, one per
person) live in the parent directory of this repo, not inside it. The
skills resolve which person a request is about (see each `SKILL.md`'s
"Who is this for?" section) and pass the matching path to their script.
See the parent directory's `CLAUDE.md` for sheet format, column
semantics, routing rules, and backup strategy.
