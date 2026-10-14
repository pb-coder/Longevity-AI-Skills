# workout-coach code map

Where to go when you need to change something in this skill. Modeled on
the [`ARCHITECTURE.md`](https://matklad.github.io/2021/02/06/ARCHITECTURE.md.html)
convention: a short, opinionated index that an agent can read once
before touching the code.

## Anchor doc reading order

A fresh agent or contributor should land here in this order:

1. **[`Skills/CLAUDE.md`](../CLAUDE.md)** — repo layout, per-person CSV
   schemas, package import conventions, and person-parametric paths.
2. **[`SKILL.md`](SKILL.md)** — the `/coach` entry point. Phase 1 (data
   → tracker JSON) and Phase 2 (5-tier recovery gate that BINDS the
   workout plan).
3. **This file** (`CODE_MAP.md`) — function locator: where is X defined,
   what calls it.
4. **[`Skills/DESIGN.md`](../DESIGN.md)** — visual design system
   (tokens, pills, card chrome). Read before touching CSS or any
   rendering code.

Cross-skill primitives live in [`../tracker/`](../tracker/): command
context, CSV table mechanics, typed command contracts, and benchmark
helpers. Do not copy those concerns into `workout-coach/lib/`.

CSV stores live in [`../shared/`](../shared/): `csv_store.py` is only the
compatibility facade; use `csv_store_profile.py`, `csv_store_dense.py`,
`csv_store_periodic.py`, and `csv_store_common.py` when changing storage
behavior.

Monthly workout CSV behavior is also split under [`../shared/`](../shared/):
`monthly_csv.py` is the compatibility facade; use
`monthly_csv_schema.py`, `monthly_csv_values.py`, `monthly_csv_io.py`,
`monthly_csv_canonicalize.py`, and `monthly_csv_upsert.py` for real
changes.

## When you need to change...

| Goal | Edit |
| --- | --- |
| Today-tab card HTML | [`lib/render_cards_today.py`](lib/render_cards_today.py) |
| Trajectory health/recovery cards | [`lib/render_cards_health.py`](lib/render_cards_health.py) |
| Trajectory longevity-domain cards | [`lib/render_cards_domains.py`](lib/render_cards_domains.py) |
| Trajectory risk/swim/nutrition cards | [`lib/render_cards_programs.py`](lib/render_cards_programs.py) |
| CSS / styling / colors | [`lib/render_styles.py`](lib/render_styles.py) (the `STYLESHEET` string) |
| Inline JavaScript (tabs, tooltips, chart scrubber, markdown viewer) | [`lib/render_scripts.py`](lib/render_scripts.py) (the `INLINE_JS` string) |
| Training-load chart components | [`lib/render_components_load.py`](lib/render_components_load.py) |
| Recovery scales / driver bars / sparklines | [`lib/render_components_recovery.py`](lib/render_components_recovery.py) |
| Per-muscle volume bars | [`lib/render_components_volume.py`](lib/render_components_volume.py) |
| Trajectory-domain gauges and strips | [`lib/render_components_domain.py`](lib/render_components_domain.py) |
| Coach/workout validation rules / em-dash check / length cap / catalog names | [`lib/render_validators.py`](lib/render_validators.py)::`validate_coach_reads` + `validate_workout_md` |
| **Whether a plan is allowed to render** (core dose, weekly core distribution, per-muscle weekly direct-set floor; block rotation warns only, see `BLOCK_ROTATION_ENFORCED`; `next_dose` drift, a missing main pattern and a cardio section also warn only) | [`lib/render_validators.py`](lib/render_validators.py)::`validate_workout_plan` |
| **Which checks run, in what order, for every plan** (report or not) | [`lib/plan_checks.py`](lib/plan_checks.py)::`run_plan_checks` — the one sequence `check_plan.py` and `render_dashboard.py` both call. Add a check here, never in a script. |
| Where this plan sits in its block, and what the dose actually did | [`lib/render_cards_today.py`](lib/render_cards_today.py)::`card_block_position` |
| Planned-vs-performed ledger, the D5 bench list, one dose per exercise per plan (`plan_doses`) | [`lib/adherence.py`](lib/adherence.py) |
| **Next load and rep range per lift** (double progression off the log) | [`lib/progression.py`](lib/progression.py)::`build_next_dose` |
| Load step per lift (its own most common jump, else the equipment table; single vs two dumbbells) | [`lib/progression.py`](lib/progression.py)::`observed_increment`, [`lib/constants.py`](lib/constants.py)::`LOAD_INCREMENT_KG` / `SINGLE_DUMBBELL_LIFTS` / `equipment_increment_kg` |
| **Weekly direct-set floor per muscle** (one number for coach and validator) | [`lib/constants.py`](lib/constants.py)::`muscle_floors` (emitted as `muscle_floors`; enforced by `render_validators.muscle_floor_errors`) |
| **May a weight go up today** (`progress` / `reduce`) | [`lib/health_session_rec.py`](lib/health_session_rec.py)::`compute_load_policy`, tables `LOAD_REDUCE_TIERS` / `LOAD_REDUCE_TSB_BANDS` in [`lib/constants.py`](lib/constants.py) |
| Block artifact, boundary rule, rotation diff, cold-start loads | [`lib/blocks.py`](lib/blocks.py) |
| Which headings count as lower / upper / full days | [`lib/adherence.py`](lib/adherence.py)::`session_type_from_title` (the ONLY classifier; the D3 core budget reads it through `render_validators._session_core_set_bounds`) |
| What counts as a workout heading at all | [`lib/adherence.py`](lib/adherence.py)::`_WORKOUT_HEADING_RE`, read through `render_validators._plan_workout_heading_re` |
| Whether a finding blocks or only warns on a deload | [`lib/render_validators.py`](lib/render_validators.py)::`AXIS_VOLUME` / `AXIS_STRUCTURE` — tag the finding, never special-case the caller |
| Add a tooltip for a new abbreviation in coach text | [`lib/render_validators.py`](lib/render_validators.py)::`KNOWN_TERMS` |
| Tracker JSON shape (what fields the renderer reads) | [`../tracker/contracts.py`](../tracker/contracts.py)::`TrackerJSON` + [`scripts/read_tracker.py`](scripts/read_tracker.py) |
| Coach reads JSON shape | [`../tracker/contracts.py`](../tracker/contracts.py)::`CoachReads` + [`lib/render_validators.py`](lib/render_validators.py) |
| Recovery score formula / drivers | [`lib/health_recovery.py`](lib/health_recovery.py)::`recovery_score` |
| **5-tier session recommendation (Phase 2 binding gate)** | [`lib/health_session_rec.py`](lib/health_session_rec.py)::`compute_session_recommendation` |
| 14-day tier history (the decision-history strip) | [`lib/health_session_rec.py`](lib/health_session_rec.py)::`compute_tier_history` |
| Longevity composite score (10-component weighted) | [`lib/health_longevity.py`](lib/health_longevity.py)::`compute_longevity_score` |
| VO2max age/sex percentile | [`lib/health_longevity.py`](lib/health_longevity.py)::`vo2_percentile_age_sex` |
| Longevity state I/O (DOB, conditions, meds, risk flags) | [`lib/health_longevity.py`](lib/health_longevity.py)::`read_longevity_state` |
| Per-muscle volume math (MEV / MAV / MRV thresholds, weekly tally) | [`lib/constants.py`](lib/constants.py) + [`lib/strength.py`](lib/strength.py) |
| CTL / ATL / TSB / TRIMP math | [`lib/cardio.py`](lib/cardio.py) |
| Sleep aggregation (efficiency, fragmentation, schedule, outliers) | [`lib/sleep.py`](lib/sleep.py) |
| Swim summary | [`lib/swim.py`](lib/swim.py) |
| Sauna + cold-exposure summary | [`lib/thermal.py`](lib/thermal.py) |
| Light-therapy summary | [`lib/light_therapy.py`](lib/light_therapy.py) |
| Per-muscle HR creep / strength session HR / e1RM slope | [`lib/strength.py`](lib/strength.py) |
| CSV store schemas and upserts | [`../shared/csv_store_dense.py`](../shared/csv_store_dense.py) and [`../shared/csv_store_periodic.py`](../shared/csv_store_periodic.py) |
| Monthly workout CSV canonicalization/upserts | [`../shared/monthly_csv_canonicalize.py`](../shared/monthly_csv_canonicalize.py) and [`../shared/monthly_csv_upsert.py`](../shared/monthly_csv_upsert.py) |
| Health import — the ONLY importer (Health Export Kit): daily/sleep aggregation, workout + swim payloads | [`../shared/import_health_export_kit.py`](../shared/import_health_export_kit.py) |
| Unit conversion, plausibility ranges, timestamp parsing (source-agnostic) | [`../shared/health_units.py`](../shared/health_units.py) |
| Strength-session clustering for monthly TOTAL-row metadata | [`../shared/strength_sessions.py`](../shared/strength_sessions.py) |
| Apple's activity-type enum → canonical name / cardio-autolog set | [`../shared/apple_workout_types.py`](../shared/apple_workout_types.py) |
| Per-person `data/` git history (one commit per confirmed write) | [`../shared/data_git.py`](../shared/data_git.py)::`commit_data` |
| Daily energy expenditure (TDEE / active / basal + trends) | [`lib/cardio.py`](lib/cardio.py)::`energy_28d` |
| Steps / NEAT rollup and its low/moderate/high band | [`lib/cardio.py`](lib/cardio.py)::`daily_activity_28d` |
| Nutrition phase: on-track verdict, stop signals, energy prescription | [`lib/nutrition_phase.py`](lib/nutrition_phase.py)::`nutrition_phase_summary` |
| Energy + nutrition-phase card HTML | [`lib/render_cards_programs.py`](lib/render_cards_programs.py)::`card_energy` / `card_nutrition_phase` |
| Dashboard spec / card contracts | [`references/assessment-dashboard.md`](references/assessment-dashboard.md) |
| Visual design system — colours, typography, pills, card chrome | [`Skills/DESIGN.md`](../DESIGN.md) |
| Coach behavioral rules (Phase 2 planning) | [`SKILL.md`](SKILL.md) |
| Tier A/B/C/D/E substitute templates | [`references/substitute-protocols.md`](references/substitute-protocols.md) |
| Physiology references / person profiles | [`references/training-science.md`](references/training-science.md) |

## Layout

```
Skills/workout-coach/
├── SKILL.md                              skill entry point (Phase 1 + Phase 2)
├── CODE_MAP.md                           this file
├── references/
│   ├── assessment-dashboard.md           dashboard contracts: card spec, coach-reads schema, copy rules
│   ├── training-science.md               physiology references the coach can cite + person profiles
│   ├── substitute-protocols.md           Tier A–E substitute templates (rest / Z2 / deload / modified / normal)
│   ├── swim-coaching.md                  CSS-zone interpretation, SWOLF/SPL guardrails
│   ├── bulking-science.md                phase-rate targets + stop conditions the nutrition block cites
│   └── common-mistakes.md                recurring authoring errors
├── scripts/
│   ├── read_tracker.py (1399 lines)      CLI: reads CSV store, emits compact tracker JSON
│   ├── check_plan.py                     CLI: runs every plan check, writes nothing (default /coach step 4)
│   └── render_dashboard.py               CLI: same checks, then composes the opt-in HTML report (thin orchestrator)
└── lib/
    │
    ├── # ---- Analytics modules (consumed by read_tracker.py) ----
    ├── constants.py (1030)                capabilities, landmarks, aliases, MEV/MAV/MRV
    ├── parsing.py (108)                  date + number coercions, _compact
    ├── extract.py (553)                  CSV readers + exercises-database parser
    ├── sessions.py (1565)                per-session aggregation + bodyweight trend + OLS trend verdict
    ├── adherence.py (1733)               prescription ledger: plan parser, planned-vs-performed, bench list
    ├── blocks.py (2250)                  training blocks: pattern identity, artifact, boundary, rotation diff
    ├── strength.py (785)                 volume, e1RM, HR-at-volume divergence, per-lift session history + load stalls
    ├── progression.py (384)              next_dose: double progression per lift, load policy applied, increments
    ├── cardio.py (949)                   cardio rollups, HR zones, TRIMP, CTL/ATL/TSB, NEAT + steps, energy_28d
    ├── nutrition_phase.py (499)          open-phase verdict, stop signals, energy prescription
    ├── health_windowing.py (159)         time-series primitives + weekly aggregates
    ├── health_recovery.py (242)          recovery_score + recovery drivers
    ├── health_longevity.py (544)         longevity_score + longevity_state I/O
    ├── health_session_rec.py (884)       5-tier gate + 14-day tier history
    ├── sleep.py (428)                    sleep_summary (stages, schedule, fragmentation, outliers) + SRI
    ├── swim.py (529)                     swim_summary (pace, SPL, SWOLF, CSS zones)
    ├── thermal.py (363)                  thermal_summary (sauna + cold)
    ├── light_therapy.py (158)            light_therapy_summary (RLT / PBM / blue light)
    │
    └── # ---- Renderer modules (consumed by render_dashboard.py) ----
    ├── render_helpers.py (60)            esc, fmt, signed, parse_date — zero-dep helpers
    ├── render_validators.py (2381)       KNOWN_TERMS catalog, validate_coach_reads, validate_workout_md, validate_workout_plan, auto_wrap_terms
    ├── plan_checks.py                    run_plan_checks: the ordered check sequence both CLIs run
    ├── render_components.py (23)         compatibility facade for component modules
    ├── render_components_load.py (135)   training-load chart + EWMA series
    ├── render_components_recovery.py (259)
    │                                      driver bars, scales, sparklines, metric rows
    ├── render_components_volume.py (125) per-muscle volume bars
    ├── render_components_domain.py (192) comparison strips, dials, tier history
    ├── render_components_misc.py (42)    rings + workout markdown embed
    ├── render_styles.py (740)            STYLESHEET string
    ├── render_scripts.py (258)           INLINE_JS string
    ├── render_cards_common.py (34)       shared heading + coach callout helpers
    ├── render_cards_today.py (631)       Today tab card templates
    ├── render_cards_health.py (697)      health / sleep / recovery-practice cards
    ├── render_cards_domains.py (619)     longevity-domain cards
    └── render_cards_programs.py (550)    risk / swim / energy / nutrition cards
```

> Line counts are accurate as of 2026-10-14. They will drift; re-check
> with `wc -l workout-coach/lib/*.py workout-coach/scripts/*.py` when
> something looks off.

## Analytics module index (`lib/<domain>.py`)

### Health analytics split

The health analytics live in four focused modules (there is no
`lib/health.py` facade; import from the module that owns the function):

- [`lib/health_windowing.py`](lib/health_windowing.py) — `_values_in_window`,
  `_mean_or_none`, `metric_trend_per_4w`, `latest_metric`,
  `baseline_60d`, `health_metrics_weekly`.
- [`lib/health_recovery.py`](lib/health_recovery.py) — `_z_score_signal`,
  `recovery_score` and recovery-driver confidence logic.
- [`lib/health_longevity.py`](lib/health_longevity.py) —
  `vo2_percentile_age_sex`, `_safe_norm`, `compute_longevity_score`,
  `read_longevity_state`.
- [`lib/health_session_rec.py`](lib/health_session_rec.py) —
  `compute_session_recommendation`, `compute_tier_history`, and the
  private helper gates behind Tier A/B/C/D/E decisions.
  `compute_load_policy` turns the tier into `session_recommendation.
  load_policy`: `reduce` on Tier A or B or strength TSB <= -15, `progress`
  otherwise (Tier C still scales the session's set budget, which is volume).

### Other analytics modules

- [`lib/cardio.py`](lib/cardio.py) (~949) — cardio rollups, HR zones
  (HRR/Karvonen), TRIMP, CTL/ATL/TSB rolling EWMA,
  `auto_deload_candidates`, per-session `hr_zone_label`, plus the two
  daily-rollup blocks below.
  - `daily_activity_28d(...)` — the NEAT rollup. **Steps are the PRIMARY
    basis** for its low / moderate / high band, exercise minutes are
    secondary, and walking minutes are context only; `assessment_basis`
    names which one the band actually came from, so a band built from a
    fallback is never mistaken for a band built from steps.
  - `energy_28d(...)` — daily expenditure: `tdee_kcal_daily_avg` /
    `active_kcal_daily_avg` / `basal_kcal_daily_avg` over `n_days`, plus
    `tdee_trend` and `basal_trend` state blocks. Those two are built with
    the SAME OLS-with-state helper as `bodyweight_trend`
    (`sessions._trend_verdict` + `sessions._trend_block`), so an
    unresolved energy trend says WHY it is unresolved in exactly the
    vocabulary the bodyweight trend already uses. Do not fit a second
    estimator here.
- [`lib/nutrition_phase.py`](lib/nutrition_phase.py) (~499) —
  `nutrition_phase_summary`: open-phase verdict against its target rate,
  pre-committed stop signals, `coach_action_hint`, and the `energy`
  sub-block (`tdee_kcal`, `target_deficit_kcal`, `implied_intake_kcal`,
  `basis`, plus the intake caveat keys). **Intake is not tracked
  anywhere in this tracker**, so `implied_intake_kcal` is a PRESCRIPTION
  derived from measured TDEE, never an observation — the caveat keys
  exist so no renderer or coach line can quietly present it as one.
- [`lib/strength.py`](lib/strength.py) (~785) — volume, e1RM
  (context-change aware), stale exercises, HR-at-volume divergence,
  strength-session HR trend. Also `session_history` (one record per
  exercise per day: loads, reps, top load, gym-change flag),
  `load_stall_sessions` (trailing sessions at one load with no rep gain;
  `stalled_sessions` in the e1RM block is this count) and
  `exercise_class` (compound vs isolation from the catalog).
- [`lib/progression.py`](lib/progression.py) (~384) — **the next dose.**
  `build_next_dose` is the one place a load or rep target is decided; the
  coach copies it. Double progression off the last session worked: every
  working set at the top of the rep range (capped at 12 for compounds, 20
  for isolation) adds the lift's increment and restarts the range;
  otherwise same load, more reps. A bump needs at least two working sets at
  the load. `hold` is per exercise only (a re-entry after
  `constants.STALE_EXERCISE_DAYS` or more, a lift with no usual-gym session,
  no range on record); the gate's `load_policy` can only turn the entry into
  `reduce`. A re-entry, and a last session whose best set missed the bottom
  of the range, get a load re-derived from that best set (Epley inverse at
  the bottom of the range, rounded down to the step; never raised). A
  machine, cable, Smith or landmine lift is judged on the usual gym (the
  sessions not flagged as a different gym); the most recent flagged load is
  `other_gym_load_kg`. Every lift worked inside the history window gets an
  entry, retired movements excepted; `uncovered.exercises` carries each
  unloaded or timed lift with the `last_prescription` the plan wrote.
  `observed_increment` learns the step from the person's own log (most
  common positive jump over `INCREMENT_HISTORY_MONTHS`, at least twice;
  for a machine, cable, Smith or landmine lift, only from sessions on or
  after the latest gym-change note of any lift; deload and gym-flagged sessions, implausible
  jumps and re-weighing noise, `constants.is_reweigh_jump`: no bigger than
  `smallest_real_step_kg` and under 5% of the load, are ignored) and falls
  back to `constants.equipment_increment_kg`: the equipment table, with 4 kg
  for a two-dumbbell lift (dumbbells are logged as the total of both hands)
  and 2 kg for the few one-dumbbell lifts in `SINGLE_DUMBBELL_LIFTS`, which
  the catalog does not distinguish. Entries carry `increment_kg` and
  `increment_basis`. A learned step is used as it stands (a 2 kg step on a
  two-dumbbell lift is 1 kg a hand, which light dumbbells really do come
  in); the 4 kg / 2 kg table values are only the fallback when the log has no
  usable majority. `blocks.derived_starting_load` rounds through the same
  `equipment_increment_kg`, so a one-dumbbell lift rounds to 2 kg.
- [`lib/sleep.py`](lib/sleep.py) (~428) — sleep stage aggregation,
  efficiency, fragmentation, schedule regularity, REM anomaly watch,
  `compute_sleep_regularity_index`. SRI reads the per-night
  `first_segment_start` / `last_segment_end` clock times the importer
  writes from the export's `sleepStart` / `sleepEnd`, which is why
  `capabilities.sleep_regularity` is **True**. `N Segments` is
  populated by the Health Export Kit importer (stage-entry count per
  night), so `sleep_summary.fragmentation` carries a mean and a weekly
  trend; it degrades to null only when no night in the window has a
  count (manual `/log` nights and old Health Auto Export rows), and null
  there means "not measurable", never "zero awakenings".
- [`lib/extract.py`](lib/extract.py) (~553) — CSV readers (monthly +
  dense + swim), exercises-DB parser, age + max-HR helpers.
  `health_metrics.csv` is 22 columns: `Steps`, `Active Energy (kcal)`,
  and `Basal Energy (kcal)` were appended before `Notes`, which is what
  `energy_28d` and the steps basis read.
- [`lib/swim.py`](lib/swim.py) (~529) — swim_summary (pace, SPL,
  SWOLF, CSS zones, stroke-mix outliers, CSS retest prompt).
- [`lib/thermal.py`](lib/thermal.py) (~363) — sauna + cold dose vs.
  HSP-induction threshold, paired protocol detection.
- [`lib/sessions.py`](lib/sessions.py) (~1565) —
  `build_monthly_sessions`, bodyweight trend, `progression_summary`.
  Also owns `_trend_verdict` / `_trend_block`, the shared OLS fit +
  state vocabulary that `cardio.energy_28d` reuses.
- [`lib/adherence.py`](lib/adherence.py) (~1733) — **the prescription
  ledger.** The system had no memory of its own prescriptions: nothing
  read the previous generation's plan, so generation N could not differ
  from N−1 and no planned-versus-performed number existed anywhere.
  This module reads `plans/<Person>/<date>-workout.md` back in and
  reconciles it against the logs.
  - `parse_plan(text, plan_date)` / `parse_plan_file(path)` /
    `load_plans(person, today_d, limit)` — the dated plan series,
    oldest first, never past the `--today` horizon.
  - `session_type_from_title(title)` → `lower` / `upper` / `full` /
    `None`. **The single source of truth for session type.** The D3
    core budget (4 sets lower, 2 upper) is keyed on it, so a second
    copy of this vocabulary silently reassigns budgets; do not add one.
  - `plan_windows(...)` / `reconcile_plan(plan, start, end, rows, db,
    catalog)` — one plan against the logs inside its own window,
    including substitution detection (a same-muscle movement logged
    instead of the prescribed one is not a skip).
  - `build_adherence(...)` — the `adherence` payload block, the D5
    bench list, and the single "why does this never happen" question.
  - `plan_doses(plan, db)` — one prescription per exercise per plan
    (chosen by set count, then load). `progression.build_next_dose` reads
    it for the range a session was judged against; when a plan gives a lift
    different ranges in different workouts, it uses
    `session_workout_candidates` (the ledger's own session-to-workout
    match) to pick the dose that session was done as.
  - `read_bench_log` / `record_bench_response` + a CLI, so "ask once"
    survives across runs.
- [`lib/blocks.py`](lib/blocks.py) (~2250) — **training blocks:** stable
  anchors, rotating accessories, and the boundary that forces the
  rotation to happen.
  - `load_pattern_catalog(db)` / `pattern_group(exercise, catalog)` —
    pattern identity is `<MUSCLE>/<Subsection>` from the catalog.
    Equipment is deliberately NOT part of it, so `Cable Lateral Raise →
    Dumbbell Lateral Raise` is not a rotation.
  - `read_block` / `write_block` / `new_block` / `block_from_plan` —
    the `plans/<Person>/block-<start>.json` artifact.
  - `block_status(block, today_d, deloads)` — age and boundary
    (deload, or 6 weeks, whichever comes first — computed, because the
    cadence deload gets skipped).
  - `rotation_diff_errors(prev_block, new_block, catalog)` — the six
    rotation rules, as finding strings. Pure. Whether they block is not
    decided here; `BLOCK_ROTATION_ENFORCED` routes them and is `False`
    this release. Called from
    [`lib/render_validators.py`](lib/render_validators.py)::`block_rotation_errors`;
    **pass the catalog** (a `None` catalog reparses the markdown per call).
  - `reconcile_block_with_logs(...)` — folds gym-floor substitutions
    back in so the artifact does not drift from what was trained.
  - `derived_starting_load(...)` / `rotation_candidates(...)` — a legal
    first weight for a movement with no history, which is what makes
    rotating anything new in possible at all.
  - `block_payload(...)` — the `block` payload block.
- [`lib/constants.py`](lib/constants.py) (~1030) — capabilities matrix,
  landmarks (MEV/MAV/MRV per muscle), aliases,
  `SESSION_GATE_THRESHOLDS`, and the steps thresholds
  `daily_activity_28d` bands against. `SOURCE_CAPABILITIES` is keyed by
  source (`health_export_kit` is the live one and the `DEFAULT_DATA_SOURCE`,
  `health_auto_export` is retained for stored profiles); it keeps its
  per-source shape because `capabilities` is published as a payload
  contract. Also the load policy (`LOAD_REDUCE_TIERS`,
  `LOAD_REDUCE_TSB_BANDS`, `strength_tsb_band`) and the progression tables
  (`LOAD_INCREMENT_KG`, `REP_CEILING_RANGE`, `SINGLE_DUMBBELL_LIFTS`). `muscle_floors` / `FLOOR_EXEMPT_MUSCLES` are the weekly per-muscle
  direct-set floor.
- [`lib/light_therapy.py`](lib/light_therapy.py) (~158) —
  light_therapy_summary (frequency + per-session dose).
- [`lib/parsing.py`](lib/parsing.py) (~108) — coercions, `_parse_iso_date`,
  `_compact` (strips null leaves from output JSON for token efficiency).

## Tracker payload keys — prescription memory, enforced targets, energy

Added by the 2026-08 core + variety build and the energy build that
followed it. Emitted from
[`scripts/read_tracker.py`](scripts/read_tracker.py) and typed in
[`../tracker/contracts.py`](../tracker/contracts.py); `_compact` drops
any that resolve to `None`, so **absent means "unknown", not "zero"** —
an absent `adherence` is a first run with no plans on disk, and reading
it as 0% adherence would bench everything.

| Key | Producer | What it carries | Who reads it |
| --- | --- | --- | --- |
| `adherence` | `adherence.build_adherence` | Planned vs performed over the last closed plan window: `sets_prescribed` / `sets_performed` / `completion_rate`, the isolation-vs-compound split, `per_exercise` with `consecutive_unperformed`, `substitutions`, the D5 `benched` list and the single `bench_prompt`. Measured baseline: 626 prescribed → 401 performed. | Coach (Phase 2), `blocks.block_payload` for `benched` |
| `next_dose` | `progression.build_next_dose` | `{load_policy, exercises, uncovered}`. Per lift worked inside the 120-day history window (or in the block), retired movements excepted: `load_kg`, `rep_range`, `action` (`add_load` \| `add_reps` \| `hold` \| `reduce` \| `no_history`), `basis`, `last`, `last_load_kg`, `last_reps`, `sessions_at_load`, `stalled_sessions`, `range_from`, `increment_kg`, `increment_basis`, and `other_gym_load_kg` on a machine or cable lift also logged at a flagged gym. `uncovered.exercises` is `[{exercise, last_prescription}]`: unloaded or timed work and lifts not in the catalog, each with the newest plan's written dose. | Coach (copies it); `card_block_position` |
| `session_recommendation.load_policy` | `health_session_rec.compute_load_policy` | `policy` (`progress` \| `reduce`), `tier`, `label`, `strength_tsb`, `tsb_band`, `recovery_score`, `recovery_available`, `reason`. `reduce` only on Tier A/B or strength TSB <= -15. | `next_dose`, Coach |
| `block` | `blocks.block_payload` | Current block: `started`, `age_weeks`, `boundary_due` + `boundary_reason`, `weeks_to_boundary`, and per-slot `exercise` / `tag` (`anchor` \| `rotating`) / `pattern` / `blocks_held` / `history` / `must_rotate`. `source` is `artifact`, `derived_from_plan`, or `none`. Carries `weeks_to_boundary` rather than a boundary DATE so an as-of payload contains no future-dated string. | Coach; `render_validators.block_rotation_errors` as the previous block |
| `rotation_candidates` | `blocks.rotation_candidates` | Never-performed catalog movements inside patterns trained in the last 8 weeks, each with a derived starting load. Without this there is no legal way to write a weight for a new movement, which made novelty impossible rather than merely rare. | Coach |
| `core_week_spec` | `constants.CORE_WEEK_SPEC` | D3 + the distribution axes: `sets_per_session` (4 lower / 2 upper), `min_distinct_exercises_per_week`, `min_pattern_categories_per_week`, `max_sessions_per_exercise_per_week`, `min_loaded_flexion_exercises_per_week`. | Coach; **enforced** by `validate_workout_plan` |
| `arm_week_spec` | `constants.ARM_WEEK_SPEC` | `min_distinct_exercises_per_week` (2), per flexor / extensor. The arm SET floor is two rows of `muscle_floors`. | Coach; **enforced** by `validate_workout_plan` |
| `muscle_priority_tiers` | `constants.muscle_priority_tiers(profile)` | Per muscle: `emphasis` \| `grow` \| `maintain` (D8). Sourced from `profile.csv` with a block default; an unrecognised profile override prints a warning rather than resolving silently to `maintain`. | Coach |
| `muscle_volume_targets` | `constants.muscle_volume_targets(tiers)` | The tier turned into a weekly set target per muscle — mid-MAV / MEV / MV — in the same unit as `weekly_volume_per_muscle`. | Coach |
| `muscle_floors` | `constants.muscle_floors(tiers, servable, sessions_per_week, cadence_deload)` | `{muscle: direct sets per week}` scaled by min(1, `strength_sessions_per_week` / 4) and, on a cadence deload week, by (n - 0.5) / n, rounded down: emphasis tier = the muscle's MEV, every other tier = MV, in DIRECT sets (not the fractional unit of `muscle_volume_targets`). A muscle with no floor is **absent, not 0**: core (its dose is `core_week_spec`), erectors, forearms, muscles whose landmark is 0 at that band, and muscles the catalog has no direct exercise for (external rotators). | Coach; **enforced** by `validate_workout_plan` through the same function, which ignores any `muscle_floors` key in the payload it is handed |
| `strength_sessions_per_week` | `read_tracker` (`--sessions N`, else `profile.csv`) | The session count to plan. Absent when neither is set. The floors in `muscle_floors` are already scaled by it, and `render_validators` scales by the same payload value. | Coach; `muscle_floor_errors` |
| `last_session_type`, `last_session_type_reason` | `adherence.last_strength_session_type` | `{type, title, date, plan_date}` of the newest strength session, matched to a workout of the plan written on or before it; absent when it cannot be told, and `last_session_type_reason` then says why. Where the split rotation continues from. | Coach |
| `volume_landmark_unit` | literal `"fractional"` | States which unit the landmarks and the tally are in (D9). RP publishes DIRECT sets; this tracker counts direct + 0.5 × synergist, and the two were silently compared for months. | Coach |
| `synergist_credit_offset` | `constants.SYNERGIST_CREDIT_OFFSET` | The measured per-muscle synergist credit folded into the landmarks, so the conversion between the two units is stated rather than assumed. | Coach |
| `bodyweight_trend` | `sessions.bodyweight_trend` | The OLS fit with its verdict: `state` (`resolved` \| `unresolved`), `reason`, `note`, `point_kg_per_week`, `se_kg_per_week`, `ci95_kg_per_week`, `n_readings`, window bounds. `bodyweight_trend_kg_per_week` beside it stays `float \| None` for existing consumers; this block says WHY it is `None`. | `card_body_comp_domain` and `card_vitals`, via `render_dashboard`'s `bw_trend_block` |
| `energy_28d` | `cardio.energy_28d` | Daily expenditure: `tdee_kcal_daily_avg` / `active_kcal_daily_avg` / `basal_kcal_daily_avg` over `n_days`, the scalar `tdee_trend_kcal_per_week` / `basal_trend_kcal_per_week`, and the `tdee_trend` / `basal_trend` state blocks in the same `state` / `reason` / `note` vocabulary `bodyweight_trend` uses. The split is stored rather than the total because a falling basal during a cut is adaptive thermogenesis, and the sum destroys it. | `card_energy`; Coach; `nutrition_phase_summary` for its `energy` sub-block |
| `daily_activity_28d` | `cardio.daily_activity_28d` | NEAT rollup with `steps_daily_avg` plus the exercise / walking minutes, an `assessment` band (low / moderate / high), and `assessment_basis` naming which input produced the band. **Steps are primary, exercise minutes secondary, walking minutes context only** — read `assessment_basis` before quoting the band. | `card_neat`; Coach |
| `nutrition_phase` | `nutrition_phase.nutrition_phase_summary` | Open phase only: target vs observed rate, stop signals, `coach_action_hint`, and an `energy` sub-block (`tdee_kcal`, `target_deficit_kcal`, `implied_intake_kcal`, `basis`, intake-caveat keys). `tdee_kcal` is measured; **`implied_intake_kcal` is prescribed** — nothing in this tracker observes intake, and the caveat keys travel with the number so no consumer can present it as an observation. | `card_nutrition_phase`, `card_energy`; Coach |

`bodyweight_trend.reason` has five values and each renders as different
words, because "you have not measured enough" and "the data cannot
resolve a direction" are different findings with different remedies:

| `reason` | Body composition card | Vitals State cell |
| --- | --- | --- |
| `no_readings` | no fasted weigh-ins in the window | no weigh-ins |
| `too_few_readings` | too few weigh-ins to fit a rate | too few weigh-ins |
| `window_shorter_than_min` | window shorter than the 28-day minimum | window under 28d |
| `no_time_variance` | all weigh-ins fall on one day | one day only |
| `ci_straddles_zero` | direction not resolved, 95% interval spans zero | direction unresolved |
| unknown code | the block's own `note` | trend unresolved |
| block absent | rate not resolvable from the current window | trend unresolved |

Both cards take the block as a trailing optional argument. Drop it and
they fall back to the last two rows — which is the pre-2026-08 bug: a
card that shrugs at a null rate, next to a coach line asserting a
direction the data never supported.

## Renderer module index (`lib/render_*.py`)

### [`lib/render_helpers.py`](lib/render_helpers.py) (~60 lines)

The tiniest formatters. Zero dependencies; every other `render_*` module
imports from here. Keep it that way to avoid circular imports.

Functions: `esc(s)`, `fmt(v, digits, default)`, `signed(v, digits,
default)`, `parse_date(s)`.

### [`lib/render_validators.py`](lib/render_validators.py) (~2694 lines)

Coach-text schema validation, the tooltip-term catalog, and **the gate
that decides whether a plan is allowed to render at all**.

Constants: `KNOWN_TERMS` (abbreviation → tooltip), `COACH_CARD_KEYS`,
`EM_DASH`, `COACH_STRING_MAX`.

Copy + schema: `validate_coach_reads(coach) -> (errors, warnings)`,
`validate_workout_md(text) -> (errors, warnings)`, `auto_wrap_terms(text)`.

Content: `validate_workout_plan(text, *, core_spec, arm_spec,
target_working_sets, budget_by_index, prev_block, plan_date,
deload_week) -> (errors, warnings)`. This is the blocking entry point
and the one `plan_checks.run_plan_checks` calls (for both `check_plan.py` and `render_dashboard.py`). It unions:

| Finding | Function | Axis | Severity |
| --- | --- | --- | --- |
| Per-session core dose (floor, and "no core at all") | `workout_core_warnings` | `AXIS_VOLUME` | error, **warning on a deload** |
| Per-session core ceiling, placement, "never optional" | `workout_core_warnings` | `AXIS_STRUCTURE` | error |
| Weekly core distinct / pattern categories / per-exercise cap | `core_week_errors` | `AXIS_STRUCTURE` | error |
| Weekly loaded-flexion requirement | `core_week_errors` | `AXIS_VOLUME` | error, **warning on a deload** |
| Weekly direct-set floor per muscle (emphasis = MEV, else MV; core, erectors, forearms exempt) | `muscle_floor_errors` | `AXIS_VOLUME` | error, **warning on a deload** |
| Direct-arm distinct exercises, terminal-slot placement | `workout_arm_dose_warnings` | `AXIS_STRUCTURE` | error |
| Block rotation against the previous block | `block_rotation_errors` → `blocks.rotation_diff_errors` | — | **warning this release**, see `BLOCK_ROTATION_ENFORCED` |
| Working-set budget drift | `workout_set_budget_warnings` | — | always **warning** |

**Rotation is advisory this release.** `BLOCK_ROTATION_ENFORCED` in
[`lib/render_validators.py`](lib/render_validators.py) is the one switch;
set it to `True` and rotation findings become errors again with no other
edit. Nothing else is turned off: the check still runs on every render,
the payload still carries the full `block` state, and the findings still
print to stderr tagged `ROTATION_ADVISORY_TAG`. Core and arm findings are
unaffected and still refuse the render. The reason for the split is input
provenance: the core and arm specs judge a plan against the tracker's own
data, while rotation judges it against a block derived from the
coach-authored markdown, and that surface has not been through the same
hardening yet.

The function names ending in `_warnings` are historical: those findings
went to stderr through July, the next generated plan ignored them, and
that is exactly what an advisory warning mid-pipeline buys you. The
public wrappers still return flat `list[str]`; the axis tags come from
the private `_core_session_findings` / `_core_week_findings` /
`_arm_findings` generators that those wrappers flatten, so
`validate_workout_plan` routes by tag and never by string-matching a
message.

### The axis split, and why a deload needs it

`AXIS_VOLUME` vs `AXIS_STRUCTURE` answers one question: **does
satisfying this finding cost fatigue?**

Without the split the new specs made a legitimate deload impossible to
author. The real 2026-07-13 plan — a deliberate, correct half-volume
week — collected nine blocking errors, six of them for containing less
work, which is what a deload IS. `workout_set_budget_warnings` had
always known this ("confirm this is an intentional deload"); the weekly
specs contradicted it.

- **Volume floors demote** under a deload. Reducing volume is the point.
- **Diversity, identity, placement and ceilings do not.** They cost
  nothing — three sessions at two core sets each still allows three
  distinct movements across three categories. A deload is not a licence
  to go back to four sets of the same crunch, which is the exact failure
  this build exists to stop.

Demoted findings are tagged `[advisory: deload week]` in the warning
text so a reader can tell a demotion from an inherently advisory finding.

### Diversity axes are dose-aware, not deload-aware

"Diversity costs no fatigue" is only true while obeying it still leaves
a real dose on each movement. Splitting 2 sets across 2 exercises makes
two 1-set doses, which is worse training than one 2-set dose; splitting
6 sets across 3 categories makes 2 sets each, which is fine. So every
"the week must contain N different things" axis is capped:

```
effective_min = min(spec_min, available_sets // MIN_SETS_PER_DISTINCT_EXERCISE)
```

`MIN_SETS_PER_DISTINCT_EXERCISE = 2`, and `available_sets` is what that
plan actually prescribes — core sets for the core axes, direct sets per
muscle for the arm axis. Applied to
`core_week_spec.min_distinct_exercises_per_week`,
`core_week_spec.min_pattern_categories_per_week` (same shape; excluding
it would let a 3-set week relax the distinct floor to 1 while still
demanding 3 categories, forcing exactly the 1-set doses the rule
prevents), and `arm_week_spec.min_distinct_exercises_per_week`. When the
cap bites, the message says so: *"requires 2 (spec floor 3, capped by 4
core sets at 2 sets per exercise)"*.

A dose-aware floor rather than a deload carve-out, because it fires on
any genuinely low-volume week including ones nobody has enumerated, and
because **it cannot be gamed**: cutting sets lowers the diversity
requirement but leaves the VOLUME floors blocking on a normal week, so a
coach shrinking a week to escape the diversity axis walks into the
volume axis instead.

Two asymmetries, both deliberate:

- **Core at zero sets does NOT relax** — the spec stands in full. Core's
  per-session absence findings are `AXIS_VOLUME` and demote on a deload,
  so if the weekly axis also relaxed at zero, a "deload" listing three
  core movements at zero credited sets would clear every check in the
  file. Arms do relax at zero, because the `AXIS_VOLUME` arm floor names
  that absence explicitly and two findings for one absence is noise.
- **`max_sessions_per_exercise_per_week` gets *more* satisfiable as
  volume drops** (with two core sessions a 2-session cap cannot bind), so
  it never becomes unsatisfiable from lack of volume the way a floor
  does. It can still force a bad dose in one narrow case: an exercise in
  K > cap sessions must split into `ceil(K / cap)` movements, and a week
  too thin to give each of those a real dose would end up prescribing
  1-set bullets. Same capacity, same test — the cap stands down only
  there.

### Deload is not Tier C

| Gate state | `tier_budget_by_index` | `is_deload_week` | Core / per-muscle volume floors |
| --- | --- | --- | --- |
| Tier A `rest` | 0 | **True** | advisory |
| Tier B `reactive_deload` (any `load_policy: reduce`) | 50% of base, whole week | **True** | advisory |
| Tier C `downgrade` | 60% of base, first `expected_rebound_by_session` workouts only | False | **enforced** |
| Tier C `hold_load`, Tier D `green`, Tier E | base | False | enforced |

Tier C fires on poor systemic recovery, and the right response is to cut
the systemically expensive work — compound volume — not the cheap work.
Core and direct-arm sets are low-fatigue and are precisely the
chronically under-dosed categories this build protects; halving them on
a bad-recovery day would re-create the under-dosing, on exactly the days
a coach is most likely to reach for it. So under Tier C the isolation cut
comes out of the rest of the accessory block and `core_week_spec` /
the per-muscle floors stay enforced. `DELOAD_WEEK_LABELS` excludes `downgrade`
for that reason; it is a deliberate exclusion with a test on it, not an
oversight.

**Two sources, because there are two kinds of deload.** A REACTIVE
deload is a recovery decision and arrives in
`session_recommendation.label`. A CADENCE deload (the generation on which
weeks-since-the-last-logged-deload crosses `blocks.DELOAD_CADENCE_WEEKS`)
is a block decision, ships with `tier: D, label: green`, and arrives as
**`block.deload_prescribed`**, with **`block.deload_source`** naming
which clock called it — both written by `blocks.block_payload` beside the
other boundary fields. Only the reactive one is a FULL-BLOCK deload
(`is_deload_week(session_rec)`: Tier A, a `DELOAD_WEEK_LABELS` label or
`load_policy: reduce`), and only it makes the volume floors advisory. The
cadence one halves ONE session, so `is_cadence_deload_week(session_rec,
block)` keeps every floor blocking, scaled by (n - 0.5) / n
(`constants.floor_scale`), core unscaled (it is exempt from the halving).
Do not confuse `deload_prescribed` ("cut the volume") with
`boundary_due` ("rotate the selection"): different clocks, and all four
combinations occur.

Never inferred from set counts. "This plan looks light, so it must be a
deload" is the gaming vector that would let any under-dosed week excuse
itself; the deload has to be DECLARED by whoever decided it.

Supporting: `tier_budget_by_index(session_recommendation, base_budget)`
returns the `idx -> budget` callable the recovery gate implies;
`is_deload_week(session_recommendation)` answers the separate question
above. Both read the same `session_recommendation` block — one source,
two questions.

### What counts as a workout heading

`_iter_workout_exercise_bullets` recognises the grammar
`adherence._WORKOUT_HEADING_RE` defines — `## Workout N:`,
`## Deload Session N:`, `## Session N:` — plus a legacy
`^## Workout` fallback for unnumbered forms like `## Workout A: PUSH`.
It is a UNION on purpose: the validator must see everything the ledger
sees (otherwise `## Session N:` bypasses the core and arm checks
entirely) and must not stop seeing anything it already did (an
unrecognised heading silently disables every check on that workout).
Matching only `## Workout` produced both failures at once — over-blocking
a deload written one way, and skipping a plan written the other.

A block that prescribes zero working sets is skipped by the per-session
core check: `## Session 1: Zone 2 cardio + mobility` is a real heading
inside this grammar, and asking it for a core budget invents a
violation. Zero-set blocks already contribute nothing to the weekly
axes, so nothing hides there.

Both `_core_pattern_categories` and `_biceps_triceps_exercise_names`
resolve exercise membership from the catalog parsers, never a literal
list in this module — `test_render_validators` asserts that by
inspecting the source, so do not inline a name.

### Dashboard Components

SVG and HTML components used by the cards. Each function returns a
complete fragment. `lib/render_components.py` is a compatibility facade;
real component code is grouped by purpose:

- **Training-load chart** (`render_components_load.py`): `build_load_series` (CTL/ATL/TSB EWMA over
  N days, with pre-window seeding) + `load_chart_svg` (interactive line
  chart with hover scrubber).
- **Activity rings** (`render_components_misc.py`): `ring(actual, target, label, sub)`.
- **Recovery drivers** (`render_components_recovery.py`): `metric_label`, `metric_tip`, `driver_bars`
  (diverging horizontal bars; filters out penalty-only `z=None`
  signals).
- **Per-muscle volume** (`render_components_volume.py`): `muscle_bars(weekly_volume)` (4-band stack
  with MEV / MAV tick marks).
- **Hero scales** (`render_components_recovery.py`): `freshness_scale(tsb)` (−15..+15 strip),
  `recovery_scale(score)` (0..10 strip). Both share viewBox + band-
  label conventions so the two hero cards look like siblings.
- **Tier strip** (`render_components_domain.py`): `tier_history_strip(history)` — 14-day decision
  history (one square per day, coloured by tier).
- **Small indicators** (`render_components_recovery.py` / `render_components_misc.py`): `confidence_dots(conf)`, `sparkline(values,
  status_class)`, `embed_workout_markdown(md_text)`.

### Dashboard assets

Two module-level string constants — pure data, no functions — split by
asset type. [`lib/render_styles.py`](lib/render_styles.py) holds `STYLESHEET`
and [`lib/render_scripts.py`](lib/render_scripts.py) holds `INLINE_JS`.

**Implements the design system documented in
[`Skills/DESIGN.md`](../DESIGN.md).** Read that first before touching
CSS — token values (colours, typography, spacing) come from its YAML
front matter and must be referenced via CSS variables in
[`lib/render_styles.py`](lib/render_styles.py). **No raw
hex literals outside the `:root` block** (lint: `rg
"#[0-9a-fA-F]{3,6}" lib/` should only hit `:root`).

- `render_styles.STYLESHEET` — the full inline CSS. Owns colors (CSS custom
  properties at the top, mapping `Skills/DESIGN.md` tokens), card
  chrome, every visual component's layout, tooltip styling, mobile
  breakpoints.
- `render_scripts.INLINE_JS` — inline JavaScript embedded at the bottom of the HTML.
  Tab switching with URL hash mirroring, hover tooltip positioning,
  interactive training-load chart scrubber + tooltip, tiny markdown
  renderer for the Workout tab.

### Card renderer split

There is no Trajectory-tab facade; each card lives in the focused module
that renders it:

- [`lib/render_cards_common.py`](lib/render_cards_common.py) —
  `coach_block`, `_heading`, heading tooltip copy.
- [`lib/render_cards_today.py`](lib/render_cards_today.py) — Today tab:
  `card_session_call`, `card_hero`, recovery drivers, ACWR, rings, NEAT,
  training load, muscle volume, strength, week-over-week, tier strip.
- [`lib/render_cards_health.py`](lib/render_cards_health.py) —
  trajectory health surfaces: vitals, sleep, recovery practices.
- [`lib/render_cards_domains.py`](lib/render_cards_domains.py) —
  longevity domain cards: longevity score, cardio, recovery, sleep,
  body composition, metabolic, behavioral.
- [`lib/render_cards_programs.py`](lib/render_cards_programs.py) —
  risk flags, swim trajectory, `card_energy`, nutrition phase.
  `card_energy` renders directly ABOVE the nutrition-phase card, because
  measured expenditure is the anchor the phase's intake target is
  derived from and the two read as one argument top to bottom. Keep that
  order when reshuffling the Trajectory tab.

Every `card_*` still returns a complete `<section>`. Renderer modules
remain presentation-only: no disk I/O and no analytics imports.

## Pipeline at a glance

```
            ┌───────────────────────────────────────────────────┐
            │ <Person>/data/ (CSVs)                             │
            │   monthly/YYYY.MM.csv, health_metrics.csv,        │
            │   workout_sessions.csv, sleep/, swimming/,        │
            │   thermal/, light_therapy/, longevity/            │
            └───────────────────────────────────────────────────┘
                                 │ read by
                                 ▼
            ┌───────────────────────────────────────────────────┐
            │ scripts/read_tracker.py                           │
            │   imports from lib/*.py analytics modules         │
            │   emits compact JSON to stdout                    │
            │   (includes session_recommendation +              │
            │    tier_history + longevity_score)                │
            └───────────────────────────────────────────────────┘
                                 │ tracker.json
                                 ▼
            ┌───────────────────────────────────────────────────┐
            │ Coach LLM (you, when /coach runs)                 │
            │   reads SKILL.md Phase 2, the tracker JSON, and   │
            │   references/assessment-dashboard.md; must HONOR  │
            │   the 5-tier gate's headline + rationale in the   │
            │   workout markdown opening (Phase 2 binding       │
            │   mandate); writes coach_reads.json and           │
            │   <date>-workout.md                               │
            └───────────────────────────────────────────────────┘
                                 │
                                 ▼
            ┌───────────────────────────────────────────────────┐
            │ scripts/check_plan.py (always) and                │
            │ scripts/render_dashboard.py (report only)         │
            │   both run lib/plan_checks.run_plan_checks:       │
            │   validates coach_reads.json                      │
            │   validates the workout markdown's COPY, then     │
            │     its CONTENT (validate_workout_plan): core     │
            │     dose + distribution, direct-arm floor, block  │
            │     rotation. Any BLOCKING finding => exit 2,     │
            │     NO HTML. On a prescribed deload the volume    │
            │     floors demote to warnings; diversity does not.│
            │     Rotation warns only this release, see         │
            │     BLOCK_ROTATION_ENFORCED.                      │
            │   check_plan.py also refuses a coach_reads.json   │
            │     that is not older than the workout markdown.  │
            │   render_dashboard.py then composes               │
            │     plans/<Person>/<date>-assessment.html         │
            └───────────────────────────────────────────────────┘
```

**The checks are a gate, not a printer.** A plan that fails
`validate_workout_plan` makes `check_plan.py` exit 2 (and the renderer
produce no HTML); the coach must fix the plan and re-run. The HTML is
opt-in, the checks are not. Before 2026-08 every one of those findings was a
stderr line, and the plan that shipped on 2026-07-18 met every numeric
target the system checked while training one core movement, in one
pattern category, four times a week.

## Conventions

- Coach internals import through `workout_coach.lib.*`. Modules inside
  `workout-coach/lib/` use package-relative imports; the underscore
  facade preserves the historical hyphenated skill directory and public
  script paths.
- Renderer modules **do not** import from analytics modules and vice
  versa. The interface between them is the tracker JSON shape in
  [`../tracker/contracts.py`](../tracker/contracts.py).
  **One carve-out: [`lib/render_validators.py`](lib/render_validators.py).**
  It reaches into `constants`, `extract`, `adherence` and `blocks`
  because its rules are questions about the catalog, the plan grammar
  and pattern identity — the alternative is a second copy of catalog
  parsing, heading classification and pattern identity living in the
  renderer, which `Skills/CLAUDE.md` forbids outright. Those imports are
  function-local, so a render that validates no plan does not pay for
  them. The `card_*` modules stay presentation-only; do not widen the
  carve-out to them.
- No external HTTP / CDN / web font dependencies in the dashboard.
  Verify with `grep -E '<script src|<link href="http|@import url'` on
  the rendered HTML — must be zero matches.
- New abbreviations in coach text: register in `KNOWN_TERMS`. Update
  the `references/assessment-dashboard.md` tooltip-catalog list to
  match.
- **Phase 2 is binding**: when `compute_session_recommendation` returns
  tier A or B, the coach MUST quote its `headline` and top-3
  `rationale` in the workout-markdown opening, and the planned session
  must match a substitute from `references/substitute-protocols.md`.
  See `SKILL.md` Phase 2.

## Quick how-to recipes

**Add a new card.**
1. Implement `card_yournew(data, coach_text)` in
   the focused card module for its tab/domain.
2. Add CSS for any new classes in `STYLESHEET` in
   [`lib/render_styles.py`](lib/render_styles.py). Reference CSS
   variables, not raw hex.
3. Wire the call into
   [`scripts/render_dashboard.py`](scripts/render_dashboard.py)::`render()`
   in the desired position.
4. Add an entry to the Coach-reads schema in
   [`references/assessment-dashboard.md`](references/assessment-dashboard.md)
   if the card has a coach callout.
5. Add the callout key to `COACH_CARD_KEYS` in
   [`lib/render_validators.py`](lib/render_validators.py) so a missing
   callout warns.
6. If the card is GATED — it returns `""` unless some payload block is
   present — add the same key to `GATED_COACH_CARD_KEYS` beside it.
   Otherwise every run without that data emits a missing-callout warning
   for a card that was never going to render, and the real warnings get
   lost in the noise.

Worked example, `card_energy`: implemented in
[`lib/render_cards_programs.py`](lib/render_cards_programs.py); no
new CSS (it reuses the existing domain-card classes, so step 2 was a
no-op); wired into `render()` directly above `card_nutrition_phase`;
documented in
[`references/assessment-dashboard.md`](references/assessment-dashboard.md);
key `trajectory_energy` registered in **both** `COACH_CARD_KEYS` and
`GATED_COACH_CARD_KEYS`, because it renders only when `energy_28d` is in
the payload.

**Change a card's layout.**
- HTML / structure: the focused `lib/render_cards_*.py` module.
- CSS: [`lib/render_styles.py`](lib/render_styles.py).
- New SVG glyph or chart: add a function to the focused
  `lib/render_components_*.py` module and re-export it from
  [`lib/render_components.py`](lib/render_components.py) if existing
  imports need it.

**Change the recovery score formula.**
- Drivers and weights:
  [`lib/health_recovery.py`](lib/health_recovery.py)::`recovery_score`.
- Per-signal z-score normalization: `_z_score_signal` in the same file.
- Sample-sufficiency thresholds: `SESSION_GATE_THRESHOLDS` in
  [`lib/constants.py`](lib/constants.py).

**Change the 5-tier session-recommendation gate.**
- Driver list, thresholds, tier-down logic:
  [`lib/health_session_rec.py`](lib/health_session_rec.py)::`compute_session_recommendation`.
- Whether a weight may rise: `compute_load_policy` in the same file, off
  `LOAD_REDUCE_TIERS` / `LOAD_REDUCE_TSB_BANDS` in
  [`lib/constants.py`](lib/constants.py).
- Per-tier substitute templates the coach renders:
  [`references/substitute-protocols.md`](references/substitute-protocols.md).
- Phase 2 binding-mandate copy: [`SKILL.md`](SKILL.md) (Phase 2 section).

**Verify a renderer change.** Render before + after, diff the HTML,
ignoring the footer's `generated at` timestamp (it uses
`datetime.now()`, so it'll always differ across runs):

```bash
diff <(grep -v 'generated at' before.html) <(grep -v 'generated at' after.html)
```

Backlog item: snapshot tests (`tests/test_render_dashboard_snapshot.py`)
will automate this against the existing `tests/fixtures/<Person>/` and
`tests/fixtures/<OtherPerson>/` trees.
