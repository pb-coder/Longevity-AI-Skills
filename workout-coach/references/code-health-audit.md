# workout-coach code health audit

A snapshot of the skill's code health after PR #3 (dashboard fidelity), PR #4
(5-tier recovery gate), and PR #5 (design system + cleanup). Focused on
sustainability, scalability, and agent navigability — not on training science
or product direction.

> **Status**: 2026-05-24. Re-audit when the next 2-3 PRs land or when
> `lib/health.py` / `lib/render_cards.py` change shape materially.

---

## Health snapshot

### Top 5 strengths

1. **Person-parametric architecture is design-clean.** Zero hardcoded paths
   anywhere in `lib/` or `scripts/` — everything resolves through
   `shared/person_paths.py`. Adding a third person requires zero code change.
2. **Capability gating actually works.** `recovery_score()` filters drivers
   on `capabilities`; `compute_longevity_score()` accepts an optional
   `capabilities` arg (PR #5); HealthAutoExport-only sources don't render
   misleading "missing input" pills for Fabian.
3. **Renderer ↔ analytics separation is enforced by convention and reality.**
   `render_*` modules don't import from analytics modules and vice versa.
   The seam is the tracker JSON shape — clear contract, easy to mock.
4. **DESIGN.md is normative, not aspirational.** Tokens live in YAML front
   matter; the `:root` block in `render_assets.py` is the only place hex
   appears; the rest of the CSS references CSS vars. The lint rule
   (`rg "#[0-9a-fA-F]{3,6}"` against `lib/`) is documented and trivially
   enforceable.
5. **Phase 2 5-tier gate (PR #4) is a real binding mandate, not a hint.**
   `compute_session_recommendation` runs deterministically against pre-gated
   signals and emits `tier` + `headline` + `rationale` that the coach must
   honor. The state machine is well-structured internally (tier enum, driver
   list, override fields).

### Top 5 issues

1. **`CODE_MAP.md` was stale at audit time.** Line counts were wrong
   (claimed `render_cards.py` ~660 lines, actually 1570; `render_assets.py`
   ~690 actually 998); card list stopped at `card_wow` so the PR #4/#5
   additions weren't indexed at all; `compute_session_recommendation` /
   `compute_tier_history` weren't mentioned in the `health.py` section.
   *Fixed in PR-A (this sweep).*
2. **Zero test coverage on the workout-coach skill itself.** `Skills/tests/`
   exists and covers `shared/` (CSV store, importers, monthly_csv,
   sessions) with Nihad+Fabian fixtures — but no test exercises
   `render_validators`, `health.py` scoring, or any `render_*` rendering.
   The Phase 2 mandate added in PR #4 is enforced only by the agent's
   willingness to honor it, with no machine check.
3. **Anchor doc overlap with no clear precedence.** `Skills/CLAUDE.md` is
   530 lines and carries CSV layout, conventions, importer semantics, and
   sleep/swim/thermal/light-therapy schemas — much of which a coach-skill
   reader doesn't need. `SKILL.md` is 102kB. There's no obvious "read in
   this order" hint. A new agent landing on the skill folder doesn't know
   if `CODE_MAP.md` or `SKILL.md` is the entry point.
4. **TypedDict contracts are missing.** Tracker JSON shape and
   `coach_reads.json` shape are both load-bearing dict-of-dict structures,
   only documented in prose (`references/assessment-dashboard.md`). Agents
   working on the skill have no machine-checkable contract; renaming a key
   silently changes the schema. `validate_coach_reads` catches some of
   this but doesn't pin the schema itself.
5. **`compute_longevity_score` is 260 lines with inlined per-component
   normalization.** The function is the longest in `health.py`; each of
   the 10 components (VO2, sleep, ACWR, zones, movement, bodyweight,
   1RM, muscle balance, behavior, recovery) has its own normalization
   logic nested inline. Adding an 11th component or tweaking weights
   requires reading the whole function to find the right block.

---

## Module-by-module audit

### `lib/render_cards.py` — 1551 lines (1570 pre-audit, after deleting `workout_recommendation`)
- **Real shape**: 22 public `card_*` functions. Today tab (10 cards in
  render order): `card_session_call`, `card_hero`, `card_drivers`,
  `card_acwr`, `card_rings`, `card_neat`, `card_training_load`,
  `card_muscle_volume`, `card_strength`, `card_wow`. Trajectory tab
  (12 cards): `card_longevity_score`, `card_cardio_domain`,
  `card_recovery_domain`, `card_sleep_domain`, `card_body_comp_domain`,
  `card_metabolic_domain`, `card_behavioral_domain`, `card_vitals`,
  `card_sleep`, `card_recovery_practices`, `card_risk_flags`,
  `card_tier_history_strip`.
- **Dead code (verified, removed in PR-A)**: `workout_recommendation()`
  was at `render_cards.py:871`. Vestigial from the pre-PR #4 advisory
  path; the 5-tier logic now lives in
  `health.py::compute_session_recommendation`.
- **Helper duplication**: `_has_risk_flag()` (~line 1225 post-deletion)
  is defined inside the cards module and called only from
  `card_body_comp_domain`. Belongs in a shared helper module so any
  future risk-gated copy can reuse it.
- **Pill-class usage verified clean**: `.pill`, `.pill.good/.amber/.warn/
  .muted`, `.pill-adherence.{on-target,below-target,above-target}` all
  defined in `render_assets.py` and used in `render_cards.py`. No
  orphans.
- **DESIGN.md hex-literal rule violation** (fixed in PR-A): `card_sleep`
  used to inline sleep-stage colors as `style="background:#a8b6d9"`
  (Core / Deep / REM / Awake) at lines 422–428 and again in the legend
  at 572–575 — 9 hex literals outside `:root`. Migrated to
  `--stage-{core,deep,rem,awake}` tokens in `:root` plus `.stage-*` /
  `.dot.stage-*` rules in `render_assets.py`; the cards now use class
  names only. Lint
  (`rg --pcre2 '(?<!&)#[0-9a-fA-F]{6}\b' lib/render_cards.py`) returns
  zero matches.
- **Split recommendation**: into `render_cards_today.py` (~900 lines,
  the 10 today-tab cards + `coach_block` + `_heading`) and
  `render_cards_trajectory.py` (~600 lines, longevity + domain cards +
  `card_sleep`, `card_recovery_practices`, `card_risk_flags`,
  `card_tier_history_strip` + `_has_risk_flag` extracted to a shared
  helper). Two tabs, two files. Reduces grep noise and keeps the
  today-flow tight.

### `lib/render_assets.py` — 998 lines
- `.pill` base style **is** defined (line 157). All CSS classes used in
  `render_cards.py` are defined here. No orphans.
- No tier-border CSS leftovers from PR #4 — PR #5 cleaned them up.
- **Token duplication risk**: color tokens (`--good: #34c759`) and their
  tint variants (`--good-tint: rgba(52,199,89,0.12)`) are both hardcoded
  in `:root`. Changing a semantic color requires hand-recalculating the
  matching RGB-alpha tint. A `lib/design_tokens.py` that programmatically
  generates tints from hex would remove this manual sync.
- **Split recommendation**: extract `lib/design_tokens.py` that exports
  `TOKENS: dict` + a `tokens_to_css_root() -> str` function.
  `STYLESHEET` in `render_assets.py` interpolates the `:root` block
  from that. Keeps the stylesheet as final output but moves token math
  to a typed home and aligns `lib/` with DESIGN.md's YAML front matter
  (the tokens become programmatic, not text-duplicated).

### `lib/health.py` — 1349 lines
- **Verified used (not dead)**: `vo2_percentile_age_sex` is called from
  `read_tracker.py:562`; `read_longevity_state` is called from
  `read_tracker.py:555`. Keep.
- **Natural seams** (existing, can be made physical):
  - **Windowing / aggregation** (lines 34–130): `_values_in_window`,
    `_mean_or_none`, `metric_trend_per_4w`, `latest_metric`,
    `baseline_60d`, `workout_sessions_in_window`, `health_metrics_weekly`.
    ~100 lines.
  - **Recovery scoring** (lines 183–395): `_z_score_signal`,
    `recovery_score`. ~210 lines.
  - **Longevity scoring** (lines 396–699): `vo2_percentile_age_sex`,
    `_safe_norm`, `compute_longevity_score`. ~300 lines.
  - **Session recommendation** (lines 700–1162): the helpers
    `_muscles_over_mrv`, `_rhr_sustained_elevation_days`,
    `_wrist_temp_deviation_c`, `_z_for`, `_count_stalled_lifts`,
    `_tsb_sustained_days`, plus `compute_session_recommendation` and
    `compute_tier_history`. ~460 lines.
  - **Longevity state I/O** (lines 1163–1349): `read_longevity_state`,
    YAML front-matter parser. ~190 lines.
- **Split recommendation**: 4-way split keeping a thin `health.py`
  facade for back-compat imports:
  - `lib/health_windowing.py` (windowing + aggregation helpers)
  - `lib/health_recovery.py` (recovery scoring)
  - `lib/health_longevity.py` (longevity scoring + state I/O)
  - `lib/health_session_rec.py` (5-tier gate + tier history + private
    `_muscles_over_mrv`, `_rhr_sustained_elevation_days`, etc.)
  - `lib/health.py` becomes `from health_windowing import *` etc., so
    every existing `from health import ...` keeps working.
- **`compute_longevity_score` refactor** (separate item): extract each
  of the 10 component normalizations into `_norm_vo2()`, `_norm_sleep()`,
  `_norm_acwr()`, etc. Top-level function becomes a sequence of
  `(weight, _norm_X(...))` tuples and a weighted average. Reading the
  function should reveal the composition immediately, not require
  walking nested ifs.

### Other `lib/` modules
- `render_components.py` (752 lines) — cohesive SVG/HTML components,
  fine as-is.
- `cardio.py` (609), `extract.py` (550), `strength.py` (512),
  `constants.py` (463), `sleep.py` (422), `swim.py` (347),
  `thermal.py` (336), `sessions.py` (267), `render_validators.py` (186),
  `light_therapy.py` (164), `parsing.py` (108), `render_helpers.py` (50)
  — all <700 lines, single-purpose, no action needed.

### `scripts/`
- `read_tracker.py` (700 lines) and `render_dashboard.py` (256 lines) are
  thin orchestrators. Good shape. `read_tracker.py` is the only place
  where tracker JSON keys are assembled into the final dict — perfect
  place to land the TypedDict.
- The "silent-gap audit" (per `~/.claude/CLAUDE.md` — every null/0/[]/""
  leaf classified as Expected / Data caveat / Pipeline gap) is currently
  manual. Should become `scripts/silent_gap_audit.py` that reads the
  output of `read_tracker.py` and classifies leaves against an
  `EXPECTED_NULLS` map.

### `references/`
- `assessment-dashboard.md` — card spec + coach-reads schema. Current.
- `training-science.md` — physiology refs + person profiles. Profiles
  for Nihad and Fabian are heavily inlined; cosmetic person-coupling to
  generalize.
- `substitute-protocols.md` — Tier A–E substitute templates. Current.
- `swim-coaching.md` — current.
- `code-health-audit.md` — this file.

### `SKILL.md`
- 102kB. Phase 1 (data → JSON) and Phase 2 (binding 5-tier gate) are
  both present. Phase 2 mandate is enforced socially (the agent must
  honor it) but not validated by code. Consider adding a
  `validate_workout_md` pass in `render_dashboard.py` that checks the
  workout markdown opening contains the gate's `headline` and `rationale`
  — would close the loop on the binding contract.

### `Skills/CLAUDE.md`
- 530-line monolith covering layout + conventions + every CSV schema +
  importer semantics. Most of this isn't relevant to the workout-coach
  skill specifically. Doesn't need a rewrite, but a short "Anchor docs
  reading order" pointer near the top would help: `CLAUDE.md` (layout +
  conventions) → `<skill>/SKILL.md` (skill entry) → `<skill>/CODE_MAP.md`
  (function locator) → `DESIGN.md` (visual surfaces).

### `Skills/DESIGN.md`
- Clean, normative, well-formed. No action.

---

## Cross-cutting opportunities

### Typed contracts (TypedDict)
- **Tracker JSON**: define `TrackerJSON` TypedDict in `lib/contracts.py`
  with all top-level keys (`data_source`, `capabilities`, `recovery`,
  `training_load`, `monthly_sessions`, `weekly_volume_per_muscle`,
  `swim_summary`, `thermal_summary`, `light_therapy_summary`,
  `health_metrics_weekly`, `session_recommendation`, etc.) and nested
  shapes (`Recovery`, `TrainingLoad`, `SessionRecommendation`,
  `MuscleVolume`, etc.). `read_tracker.py` annotates its `out` dict
  with this type. Renderer modules accept `TrackerJSON` everywhere they
  currently accept `dict`.
- **coach_reads.json**: `CoachReads` TypedDict in the same module,
  mirrors the schema documented in
  `references/assessment-dashboard.md`. `validate_coach_reads` accepts
  `CoachReads` and the type-check pins the optional-key set in code
  rather than in prose.
- Runtime is unchanged (TypedDicts are erased). Failure mode: mypy /
  pyright surfaces drift at edit time. No new dependency.

### Test scaffold
1. **`tests/test_render_validators.py`** — em-dash rejection, length cap,
   missing optional keys warning. ~30 lines.
2. **`tests/test_session_recommendation.py`** — synthetic input dicts →
   assert tier (A–E) + headline + top-3 rationale. Pins the Phase 2
   mandate so a refactor can't silently break the 5-tier logic.
3. **`tests/test_render_dashboard_snapshot.py`** — runs
   `render_dashboard.py` against `tests/fixtures/Nihad/` and
   `tests/fixtures/Fabian/`, diffs against a stored
   `tests/snapshots/{nihad,fabian}-dashboard.html` (strip the
   `generated at` timestamp line). Catches empty-state suppression,
   capability gating, pill orphans, hex regressions.
4. **`scripts/silent_gap_audit.py`** — walks `read_tracker.py` output,
   classifies every leaf as Expected / Data caveat / Pipeline gap
   against an `EXPECTED_NULLS` map. Runnable as a pre-commit check.

Test scope lives at `Skills/tests/` next to the existing test suite.
Reuses the existing `tests/fixtures/Nihad/` and `tests/fixtures/Fabian/`
trees. No new harness needed.

### Person-specific copy generalization
Inline person profiles in `training-science.md` (§Context) and
person-specific code comments in `lib/sleep.py` (Parkinson surveillance
context) and `lib/constants.py` (XML vs HealthAutoExport split)
reference Nihad / Fabian by name. Extract to a `references/people.md`
(or YAML data file) keyed by person, loaded on demand by anything
that needs profile context. Code comments stay generic ("the user's
family history may indicate X" rather than "Nihad's paternal
Parkinson history").

### Agent ergonomics
After splits + CODE_MAP rewrite, every `lib/` module should be ≤700
lines, have a top docstring describing its role in one sentence, and
be locatable from CODE_MAP in one read. Together with the TypedDict
contracts, an agent can navigate the skill via grep + docstrings +
types alone — no need to read 1.6kloc files top-to-bottom.

---

## PR #3 / #4 / #5 findings

### PR #3 — `c034af2` — Dashboard data fidelity
- **Cleanup**: `band_class_map` dict introduced inline duplicates an
  earlier band→CSS mapping; should normalize to one constant in
  `render_assets.py` or `lib/constants.py`.
- **Inconsistency**: the empty-recovery-practices early-return pattern at
  `card_recovery_practices` is not mirrored in other zero-data cards
  (`card_strength`, `card_vitals`, etc.). The "hide-don't-placeholder"
  DESIGN.md rule applies everywhere but is implemented case-by-case. No
  urgency, but a `card_skeleton(...)` helper that handles the empty-state
  convention uniformly would prevent drift.

### PR #4 — `f519d60` — 5-tier recovery gate
- **Dead code shipped (removed in PR-A)**: `workout_recommendation()` in
  `render_cards.py:871` — the old advisory function, never referenced
  after the 5-tier gate landed.
- **Dead CSS shipped + removed in PR #5**: tier-border classes
  (`.tier-a`, `.tier-b`, etc.) added then removed. No leftovers to clean
  (PR #5 finished the job).
- **PII copy without central gating**: Parkinson surveillance string in
  `lib/sleep.py` and PrEP BMD prompt in `render_cards.py` were
  introduced here as hardcoded strings keyed to Nihad. PR #5 added
  `_has_risk_flag()` to gate display; the underlying strings remain
  Nihad-specific. Move to a person-keyed `references/people.md`.

### PR #5 — `009ba11` — Design system + cleanup
- **Pattern introduced but not fully applied**: `.pill-adherence.*` family
  added; only `card_recovery_practices` uses it. Other status-indicator
  locations still use the generic `.pill.{good,amber,warn}`. Not wrong
  (the generic version works), but a code-style decision worth pinning:
  when do you use `.pill-adherence` vs `.pill.<color>`? Document in
  DESIGN.md or pick one.
- **`capabilities` plumbing is one-off**: `compute_longevity_score`
  accepts `capabilities: dict | None = None` for the `sleep_regularity`
  filter case. The pattern works but isn't generalized — other metrics
  could also be source-unavailable, but the gating is hardcoded inline.
  Generalize via an `INPUT_CAPABILITY_REQ: dict[str, set[str]]` map in
  `constants.py` and a single filter step at the top of the function.
- **HR-at-volume signature flipped twice**: gained `hr_divergence` param
  in PR #3, lost it in PR #5 (moved to `card_muscle_volume`). Currently
  stable. No action.

### Cross-PR pattern
Each PR introduces a new piece of state (longevity_state, capabilities,
risk_flags) and threads it as a separate dict parameter. There's no
generalized "context" object that carries person-relevant state through
the renderers. As more state lands, the signature surface grows. A
`CoachContext` TypedDict carrying `person`, `capabilities`, `risk_flags`,
`longevity_state` would absorb future additions without signature churn.
Not urgent (signatures aren't unbearable yet) but worth designing now
before it becomes 8 params.

---

## Prioritised improvement backlog

Scoring: **Impact** (high/med/low) × **Effort** (S/M/L) × **Risk**
(low/med/high). Sorted by impact ÷ effort.

| # | Item | Impact | Effort | Risk | Files |
|---|------|--------|--------|------|-------|
| 1 | Rewrite `CODE_MAP.md` end-to-end — accurate line counts, PR #4/#5 cards indexed, `compute_session_recommendation` + `compute_tier_history` in health.py section, top-of-doc "anchor doc reading order" pointer | high | S | low | `workout-coach/CODE_MAP.md` |
| 2 | Delete dead code: `workout_recommendation()` at `render_cards.py:871` | low | S | low | `lib/render_cards.py` |
| 3 | Write the audit deliverable to `references/code-health-audit.md` | med | S | low | `workout-coach/references/code-health-audit.md` |
| 4 | Validator tests: `tests/test_render_validators.py` covering em-dash, length, missing-optional-key | high | S | low | `tests/test_render_validators.py` |
| 5 | Session-recommendation tier-gate tests: `tests/test_session_recommendation.py` with synthetic inputs for each of A/B/C/D/E tiers | high | M | low | `tests/test_session_recommendation.py`, `tests/fixtures/synthetic/` |
| 6 | TypedDict contracts in `lib/contracts.py`: `TrackerJSON`, `CoachReads`, `SessionRecommendation`, `Recovery`, etc. Annotate `read_tracker.py` and `render_dashboard.py` | high | M | low | `lib/contracts.py`, `scripts/read_tracker.py`, `scripts/render_dashboard.py`, `lib/render_validators.py` |
| 7 | `scripts/silent_gap_audit.py` — classify every leaf in tracker JSON as Expected / Data caveat / Pipeline gap | med | M | low | `scripts/silent_gap_audit.py`, `lib/constants.py` (EXPECTED_NULLS map) |
| 8 | Renderer snapshot tests: `tests/test_render_dashboard_snapshot.py` against existing Nihad+Fabian fixtures | high | M | low | `tests/test_render_dashboard_snapshot.py`, `tests/snapshots/` |
| 9 | Generalize person-specific copy: extract Parkinson / PrEP / vegan / creatine strings + per-person profiles into `references/people.md` (or YAML); make code comments person-agnostic | med | M | low | `references/people.md`, `lib/sleep.py`, `lib/constants.py`, `references/training-science.md` |
| 10 | Split `lib/health.py` into `health_windowing.py`, `health_recovery.py`, `health_longevity.py`, `health_session_rec.py`; keep `health.py` as a thin facade for back-compat imports | high | M | med | 5 new+modified files in `lib/` |
| 11 | Split `lib/render_cards.py` into `render_cards_today.py` + `render_cards_trajectory.py`; move `_has_risk_flag` to a shared helper | med | M | med | 2 new files in `lib/`, `scripts/render_dashboard.py` |
| 12 | Extract `lib/design_tokens.py`; programmatically generate tints from semantic colors; rewrite `:root` block from tokens | med | M | med | `lib/design_tokens.py`, `lib/render_assets.py` |
| 13 | Refactor `compute_longevity_score` into per-component `_norm_X()` helpers + weighted-average top level | med | M | med | `lib/health_longevity.py` (post-split) |
| 14 | Generalize capability plumbing: `INPUT_CAPABILITY_REQ` map + single filter step in `compute_longevity_score` (and `recovery_score`, if applicable) | low | M | low | `lib/constants.py`, `lib/health_*.py` |
| 15 | `CoachContext` TypedDict carrying person/capabilities/risk_flags/longevity_state; replace separate dict params across renderers | low | L | med | `lib/contracts.py`, all renderer signatures |
| 16 | `validate_workout_md`: check the workout markdown opening contains the gate's `headline` + top-3 rationale; close the Phase 2 social-contract loop | med | M | low | `lib/render_validators.py`, `scripts/render_dashboard.py` |
| 17 | Add `card_skeleton(...)` helper for empty-state convention; backfill across cards that hand-roll empty-state branches | low | M | low | `lib/render_cards.py` (or split files) |
| 18 | ~~Migrate 9 inline sleep-stage hex literals in `card_sleep` to `--stage-{core,deep,rem,awake}` CSS variables in `:root`; restore the "no hex outside `:root`" invariant~~ ✅ done in PR-A | med | S | low | `lib/render_assets.py`, `lib/render_cards.py` (lines 422–428, 572–575) |

---

## Recommended next 3 PRs

Each is small, shippable, and moves the needle without big-bang risk.

### PR-A — "Anchor doc + dead code sweep" (backlog #1, #2, #3) ✅ landing now
- Rewrite `CODE_MAP.md` with accurate line counts, full card list
  (today + trajectory), `compute_session_recommendation` and
  `compute_tier_history` indexed in the health.py section, and a
  top-of-doc reading-order pointer.
- Delete `workout_recommendation()` at `render_cards.py:871`.
- Write `references/code-health-audit.md` (this file).
- **Verification**: every function name and section in CODE_MAP greps
  in the codebase; `workout_recommendation` greps to zero matches.
- **Why first**: doc-only + 1-line deletion. Zero risk, immediate
  agent-onboarding benefit. Sets the foundation for everything else.

### PR-B — "Tests + TypedDicts" (backlog #4, #5, #6, #8)
- Add `lib/contracts.py` with `TrackerJSON`, `CoachReads`,
  `SessionRecommendation`, `Recovery`, `TrainingLoad`, `MuscleVolume`
  TypedDicts (plus the nested shapes they need).
- Annotate `read_tracker.py::main()`'s `out` dict, the validator's
  `coach` param, and `render_dashboard.py`'s tracker arg.
- Add `tests/test_render_validators.py` (em-dash, length, missing
  optional keys).
- Add `tests/test_session_recommendation.py` (synthetic inputs →
  A/B/C/D/E tier assertions + headline + top-3 rationale).
- Add `tests/test_render_dashboard_snapshot.py` (snapshot the Nihad +
  Fabian fixtures, stripping the `generated at` timestamp).
- **Verification**: `python -m pytest Skills/tests/` passes;
  `python -m mypy Skills/workout-coach/` shows no new errors on
  annotated entry points.
- **Why second**: zero-risk net once snapshots are seeded — every
  subsequent split / refactor lands behind passing tests.

### PR-C — "health.py 4-way split" (backlog #10)
- Split `lib/health.py` into `health_windowing.py`, `health_recovery.py`,
  `health_longevity.py`, `health_session_rec.py`. Keep `health.py` as
  a thin re-export facade so every existing
  `from health import compute_session_recommendation` etc. still works.
- No semantic change; pure file move. Snapshot tests from PR-B catch
  any accidental import breakage.
- **Verification**: snapshot tests pass identically; `git diff --stat`
  shows only file moves + re-exports.
- **Why third**: the biggest win for agent navigability of the
  computation layer, with PR-B's tests already guarding behavior.

After PR-A/B/C land, the next wave is the `render_cards.py` split (#11),
`design_tokens.py` extraction (#12), `compute_longevity_score`
component-normalization refactor (#13), and the silent-gap-audit script
(#7) — each independently shippable, no order dependency.

---

## Verification (for the whole plan)

After each PR:
1. `python -m pytest Skills/tests/ -v` — all tests pass (after PR-B).
2. `python3 Skills/workout-coach/scripts/read_tracker.py --person Nihad --pretty | head` — JSON shape unchanged.
3. `python3 Skills/workout-coach/scripts/render_dashboard.py --person Nihad ...` against current fixtures — HTML diff under snapshot test passes
   (`diff <(grep -v 'generated at' before.html) <(grep -v 'generated at' after.html)` is empty).
4. `rg "#[0-9a-fA-F]{3,6}" Skills/workout-coach/lib/` — only hits inside the `:root` block in `render_assets.py` (or `lib/design_tokens.py` after #12).
5. After CODE_MAP rewrite: every function name in the doc greps to a definition; every link works.
6. Manually open a rendered HTML in Safari at mobile + desktop breakpoint, verify session-call card + tier-history strip + longevity score render correctly with capability differences between Nihad (xml) and Fabian (health_auto_export).
