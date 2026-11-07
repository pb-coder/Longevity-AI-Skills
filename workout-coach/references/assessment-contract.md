# Assessment JSON contract

`plans/<Person>/<date>-coach_reads.json` is the durable coaching assessment. Write it before `<date>-workout.md`, then run `scripts/check_plan.py` against both and the tracker JSON. `SKILL.md` specifies how each assessment section interprets its source fields.

```json
{
  "headline": "Two or three concise sentences on trajectory and today's call.",
  "cards": {
    "session_recommendation_callout": "The gate, its driver, and its effect on training.",
    "block_position": "Block timing, selection stability, and what changes in the dose.",
    "training_load": "Strength freshness and its load-policy band."
  }
}
```

`cards` is the retained field name for assessment sections. It does not imply a visual report. The authoritative allowed keys and validation rules live in `lib/plan_validators.py::COACH_CARD_KEYS`; the typed boundary is `tracker/contracts.py::CoachReads`. Do not add decorative or rendering metadata.

No em dashes in assessment strings. Each section is at most 280 characters; `headline` is at most 560. Always author `block_position`. Author data-dependent swim, energy, and nutrition sections when their matching tracker blocks exist; omit unsupported signals. Keep unchanged findings to one sentence, explain meaningful changes, and cite only values supplied by the tracker. Never infer dietary intake from expenditure or a null trend as stability.

`lib/plan_checks.py::run_plan_checks` owns the validation sequence. `check_plan.py` must exit 0 before delivery; fix blocking errors and relay remaining warnings. Checks include assessment/tracker consistency, catalog names, workout copy, core distribution, muscle floors, dose drift, pattern coverage, and the assessment-before-plan checkpoint.
