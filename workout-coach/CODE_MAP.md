# Coach code map

Public scripts are in `scripts/`; implementation imports use `workout_coach.lib.*` through the underscore package facade. The source lives in `workout-coach/lib/`.

| Responsibility | Owner |
|---|---|
| Tracker JSON CLI | `scripts/read_tracker.py` |
| Model-facing planning projection | `lib/coach_context.py` |
| Weekly calendar and observation coverage | `lib/weekly_review.py` |
| Weekly prescription validation, amendments, publication, and Markdown view | `lib/weekly_prescription.py`, `scripts/publish_week.py` |
| Private coaching profile and exercise restrictions | `lib/exercise_fit.py`, `scripts/coach_profile.py` |
| Phase and weight trend decisions | `lib/nutrition_phase.py` |
| Legacy assessment and Markdown validation | `scripts/check_plan.py`, `lib/plan_checks.py`, `lib/plan_validators.py` |
| Typed command payloads | `../tracker/contracts.py` |
| Data reads and extraction | `lib/extract.py` |
| Session assembly and progression | `lib/sessions.py` |
| Strength metrics and volume | `lib/strength.py` |
| Cardio load and activity | `lib/cardio.py` |
| Health time series | `lib/health_windowing.py` |
| Recovery scoring | `lib/health_recovery.py` |
| Longevity metrics and private-state parsing | `lib/health_longevity.py` |
| Legacy session recommendation gate and load policy | `lib/health_session_rec.py` |
| Training blocks | `lib/blocks.py` |
| Workout heading classification and adherence | `lib/adherence.py` |
| Shared capability and training constants | `lib/constants.py` |
| Person-relative paths and CSV stores | `../shared/` |

The coach reads a weekly snapshot, authors a structured draft and publishes it through the weekly validator. The immutable weekly JSON drives adherence. The Markdown is generated for training, and historical Markdown goes through the legacy parser. [SKILL.md](SKILL.md) owns agent behavior. [Assessment contract](references/assessment-contract.md) documents historical assessment files.

Add cross-cutting checks in `plan_checks.py`, not independently in entry scripts. Keep file I/O in stores, analytics pure where practical, and profile-dependent guidance gated on runtime private context. Tests live in `../tests/`; run `python3 -m unittest discover -s tests -v` from the repository root.
