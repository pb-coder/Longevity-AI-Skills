# Coach code map

Public scripts are in `scripts/`; implementation imports use `workout_coach.lib.*` through the underscore package facade. The source lives in `workout-coach/lib/`.

| Responsibility | Owner |
|---|---|
| Tracker JSON CLI | `scripts/read_tracker.py` |
| Assessment + workout validation CLI | `scripts/check_plan.py` |
| One ordered plan-check sequence | `lib/plan_checks.py` |
| Assessment keys, workout parsing and validation | `lib/plan_validators.py` |
| Typed command payloads | `../tracker/contracts.py` |
| Data reads and extraction | `lib/extract.py` |
| Session assembly and progression | `lib/sessions.py` |
| Strength metrics and volume | `lib/strength.py` |
| Cardio load and activity | `lib/cardio.py` |
| Health time series | `lib/health_windowing.py` |
| Recovery scoring | `lib/health_recovery.py` |
| Longevity metrics and private-state parsing | `lib/health_longevity.py` |
| Session recommendation gate and load policy | `lib/health_session_rec.py` |
| Training blocks | `lib/blocks.py` |
| Workout heading classification and adherence | `lib/adherence.py` |
| Shared capability and training constants | `lib/constants.py` |
| Person-relative paths and CSV stores | `../shared/` |

The coach reads tracker JSON, writes the assessment JSON, writes strength-workout markdown, then checks both. `SKILL.md` owns agent behavior; [references/assessment-contract.md](references/assessment-contract.md) describes the saved assessment boundary. Domain science references remain separate from implementation.

Add cross-cutting checks in `plan_checks.py`, not independently in entry scripts. Keep file I/O in stores, analytics pure where practical, and profile-dependent guidance gated on runtime private context. Tests live in `../tests/`; run `python3 -m unittest discover -s tests -v` from the repository root.
