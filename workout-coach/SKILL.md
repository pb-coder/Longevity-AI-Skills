---
name: workout-coach
description: >
  Reviews a named person's Workout Tracker history and prepares a week of
  strength training. Use for /coach, a new workout plan, or tracker-based
  coaching. Workout logging belongs to workout-logger.
---

# Workout Coach

Resolve the person from the request and current context. Ask only when two trackers are plausible and a wrong choice would use someone else's data.

- **Plan the week.** This is the default for `/coach` and requests such as “plan my next workout.” Publish the full intended training week. Each session has a single prescription.
- **Review progress.** Read the tracker fields needed for the question and answer in chat. Publish a plan when the user asks for one.
- **Adjust a particular session.** For an explicit request about a session, answer in chat using the person's current report and comparable logs. A one-off change belongs with the session as performed. Revise the week when the user asks to change the plan itself.

## Read the week

For a weekly plan or a session adjustment, run this from the tracking workspace:

```sh
python3 Skills/workout-coach/scripts/read_tracker.py --person "<Person>" --weekly --for-coach --months 6
```

When preparing a plan, write the result to a unique private temporary file and reuse that snapshot for publication. Use `--week-start YYYY-MM-DD` for an explicit range, `--training-days YYYY-MM-DD,YYYY-MM-DD` for specific dates, `--sessions N` for a session-count change, and `--minutes N` for this week's available time per session. Weekends default to the upcoming Monday. On a weekday, an existing active week takes precedence. Otherwise the snapshot supplies the next available seven-day range. `--today` is the date of the evidence review. The week has its own start and end.

The planning snapshot keeps the saved prescription, exercise fit and progression references, with 28 days of individual session summaries. For a targeted review, use repeatable `--field` with `--weekly` in place of `--for-coach`. A nutrition review can request `--field nutrition_phase --field observation_coverage`. Add `--months 6 --field monthly_sessions` when the question needs older sessions. Use the computed evidence for trend and dose estimates.

Use the dates returned by `weekly_plan`. `existing_week` contains the latest published revision for that period, even when it begins in the future. If the user is revisiting their plan and circumstances are the same, link to the saved plan. For a revision, preserve IDs for the same sessions and retain earlier dated prescriptions verbatim. The date remains the originally intended date and does not imply completion. With dated plans, `--training-days` can describe just the remaining days. With flexible sessions, use the logged work and any user report to clarify what already happened. If the user gives a new count, treat it as the total for the week including retained sessions.

Use the user's stated session count or available dates, then their saved count. Ask once if the count is still unknown. Use the current block and current or previous prescription as starting points. The payload's block boundary and cadence fields are review prompts. Make an explicit decision before changing a block or planning a lighter week.

## Choose the intended training

1. **Start with this person's goal and availability.** Use the current request first, then the first goal in `exercise_fit.goals` as the primary goal and the other goals as supporting priorities. If the profile has no goals, use established block and muscle priorities and say which goal the plan serves. Pick a split that fits the actual days, equipment and time. Strength for a particular lift needs practice at that lift where feasible. Hypertrophy work can use suitable muscle-focused variants. Place the highest-priority work early in the week and in its session.
2. **Choose exercises by fit.** Read `exercise_fit` for explicit restrictions, preferences and dated observations. `excluded` describes exclusions across the week at the default gym. A scoped rule may also apply to a particular date, location or variant. Specify that context when it changes eligibility. Use known equipment at each location, including any limit or unavailable station the person has confirmed. Consider what gets performed and progressed in a comparable setup. A past omission or substitution is a reason to investigate fit. Confirmed limitations and unavailable equipment take precedence over pattern coverage or set targets.
3. **Keep meaningful continuity.** Carry forward productive and tolerable anchor exercises across weeks. Use variation when it serves the goal, accommodates constraints, or addresses a verified issue. A substitute should serve the purpose of the slot. Record the decision in the session's structured `reason` when it matters. Use the catalog's canonical exercise names.
4. **Prescribe a full, feasible dose.** `next_dose.exercises` supplies progression from logged work. Use that dose when its load basis and equipment match the intended setup. `equipment_context` identifies comparable logged machine and gym when recorded. On unfamiliar equipment or a new variation, prescribe a conservative starting dose at a directly stated effort. Prefer a rep range and a cue such as “Leave 2 reps in reserve” when the available load is unknown. Preserve the tracked load convention and distinguish added load from assistance. Bodyweight changes can provide context for weighted or assisted bodyweight movements when a recent comparable measurement exists.
5. **Check volume against what serves the goal.** The working-set target estimates how much work fits. Training history, muscle-priority targets and coverage guide the distribution. Exact warm-up count, core and arm placement, muscle floors, and calendar rotation are programming preferences. Choose a realistic amount of worthwhile work, including warm-ups where useful. A planned lighter week or return after a confirmed break can have its own full intended prescription.

**Starting a lift.** In `rotation_candidates`, the `bodyweight` load basis means no external load. `no_reference` and `unknown_transfer` mean a reliable starting load in kilograms is unavailable. Give that lift a conservative effort-based prescription, such as 2-3 reps in reserve. Treat a derived starting load as a first-exposure ceiling.

### Recovery and nutrition

`observation_coverage` reports latest observations by metric and applied export ranges separately. An export date is distinct from the last observed sleep, workout, resting heart rate or weigh-in. A missing batch leaves recent activity unknown. Use recovery and training-load patterns as context in the assessment, and use confirmed training history and reported constraints for structural changes. Recent symptoms or an explicit rehab restriction govern which activity is appropriate. An unusually hard session or a short night, by themselves, belong in the discussion of the affected session.

`nutrition_phase` is an optional review of the declared cut, maintain, bulk or recomp phase. Read `targets`, `actuals` and `decision_reason` together. `defer` means keep the agreed plan while waiting for comparable data or clarification. Explain the phase-specific direction of a review. When a cut is losing faster than intended, discuss easing the deficit. When gain is faster than intended, review the trend and supporting evidence before discussing a reduced surplus. Keep weight direction, performance, optional waist observations, configured intake targets and actual intake distinct. Device expenditure is an estimate. Intake and protein targets describe intentions unless intake was reported.

Consult references when the question warrants it. [Training science](references/training-science.md) explains programming concepts, [core evidence](references/core-evidence.md) covers goal-specific core work, and [swim coaching](references/swim-coaching.md) explains swim summaries. [Minimal dose](references/detraining-and-minimal-dose.md) and [equipment-free training](references/no-equipment-training.md) cover planned constraints. Use the current workflow when older examples rely on dated recovery tiers.

## Publish the plan

Make a private JSON draft using the exact period and review date from `weekly_plan`. Use a unique session ID within the week and carry that ID through revisions. Leave `date` out or set it to null for a flexible slot. Include an honest duration estimate within the available time and identify the session's goal or relevant reason in structured fields. These do not appear on the workout sheet.

```json
{
  "as_of": "2026-11-21",
  "week_start": "2026-11-23",
  "week_end": "2026-11-29",
  "sessions": [
    {
      "id": "upper-a",
      "date": "2026-11-23",
      "type": "Upper A",
      "duration_min": 45,
      "goal": "Bench practice",
      "exercises": [
        {
          "name": "Flat Barbell Bench Press",
          "sets": [
            {"reps": 5, "load_kg": 20, "warmup": true},
            {"reps": "6-8", "load_kg": 40},
            {"reps": "6-8", "load_kg": 40}
          ],
          "cue": "Leave 2 reps in reserve."
        }
      ]
    }
  ]
}
```

Each set has one dose: `reps`, `seconds` or `metres`. Reps can be a single count or a range such as `"6-8"`. Omit load for bodyweight or a direct effort prescription. Use `load_kg` or `assistance_kg` as appropriate. Optional session `gym` and exercise `machine`, `variant` and `load_basis` preserve setup identity. Use `load_basis: "plates_only"` only when it is the intended loading convention. Cues are concise direct instructions about the intended exercise and dose.

The generated workout Markdown shows the date range, session titles, dates or flexible order, and the full intended strength work. Keep readiness advice, contingency branches, shortened sessions, cardio substitutes and nutrition discussion in chat, separate from the workout file.

```sh
python3 Skills/workout-coach/scripts/publish_week.py \
  --person "<Person>" --tracker /path/to/private-tracker.json --draft /path/to/private-draft.json
```

When the user changes existing sessions while keeping the same IDs and order, pass `--amend` in place of `--draft`. Supply `{"replacements": [...]}` with one complete session object per changed ID. The publisher copies the other sessions from disk. Use a complete draft for a new week or changes to the session count or order.

Resolve errors before publication. For `validation`, repair the draft at the locations listed in `issues`. For `stale_snapshot`, refresh the same week, review any intervening changes, and reapply the requested changes if they still fit. Report an unresolved history conflict or I/O failure. Review warnings against the actual time budget, scope and comparable setup. The command returns the Markdown and authoritative JSON paths and revision under `plans/<Person>/weekly/`. The JSON is the history record. The Markdown is generated from it. Retrying the current prescription returns the saved revision.

When the user explicitly starts a new block, persist it from the published week:

```sh
PYTHONPATH=Skills python3 -m workout_coach.lib.blocks write \
  --person "<Person>" --from-week YYYY-MM-DD
```

In chat, link the workout and give the useful change or purpose for the week. Mention a data gap, phase review or publication warning when it affects the decision. Existing dated Markdown and assessment files remain readable in the legacy workflow.
