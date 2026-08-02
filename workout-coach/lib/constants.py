"""Constants and capability tables for the /coach read pipeline.

Mostly pure data. Everything is module-level so it can be imported once
and referenced cheaply from every analytics module; the handful of
functions at the bottom (``age_band``, the priority-tier resolvers) are
pure lookups over these tables with no I/O.

Five groups:

- **Source capabilities**: per-data-source feature map
  (``SOURCE_CAPABILITIES``) plus the ``DEFAULT_DATA_SOURCE`` fallback for
  legacy trackers without a Profile sheet.
- **Sheet conventions**: ``DELOAD_MARKER`` (case-insensitive substring on
  TOTAL-row Notes) and ``TOTAL_LABEL`` (the canonical TOTAL-row exercise
  sentinel).
- **Volume + muscle taxonomy**: ``RP_DIRECT_SET_LANDMARKS`` (as
  published, direct sets), ``SYNERGIST_CREDIT_MEASUREMENT`` (the raw
  pooled median / mean per muscle) and the ``SYNERGIST_CREDIT_OFFSET``
  derived from it (the unit conversion), the derived ``VOLUME_LANDMARKS``
  (per-muscle MV/MEV/MAV/
  MRV bands **in the tracker's fractional unit**), ``MUSCLE_ALIASES``
  (database-token → snake_case key), ``SECTION_PRIMARY`` (## SECTION
  header → primary muscle), and ``SUBSECTION_PRIMARY_HINTS``
  (subsection-substring overrides).
- **Priority tiers**: ``PRIORITY_TIER_BAND`` / ``BLOCK_EMPHASIS_DEFAULT``
  plus ``muscle_priority_tiers`` and ``muscle_volume_targets`` — the
  emphasis / grow / maintain model (mid-MAV / MEV / MV).
- **Prescription specs**: ``CORE_WEEK_SPEC`` and ``ARM_WEEK_SPEC``, the
  distribution-shaped weekly targets the render validators enforce, and
  ``DOSE_PROGRESSION_SPEC``, the across-generations counterpart that
  stops the same plan shipping twice.
"""
from __future__ import annotations

# Per-source capability map. The coach reads this to decide which sections of
# the report to write. ``xml`` is Apple's native zipped export; HealthAutoExport
# has the same tracker-facing health/workout surface. ``hl_export`` is retained
# only for old trackers during migration and stays capability-limited.
SOURCE_CAPABILITIES = {
    "xml": {
        "hrv":                True,
        "wrist_temp":         True,
        "resting_hr_daily":   True,
        "walking_hr":         True,
        "sleep_stages":       True,
        "sleep_breath_dist":  True,
        "sleep_nights":       True,   # per-night architecture (all 6 stages +
                                      # Time in Bed + Efficiency + N Segments +
                                      # first/last segment clock times)
        # SRI (Sleep Regularity Index) needs per-segment bedtime / wake
        # timestamps. The Apple Health XML export carries these; the
        # HealthAutoExport pipeline collapses to daily totals and drops
        # them. Surfaces as a capability so compute_longevity_score can
        # suppress sleep_regularity from the missing-inputs list when
        # the source structurally can't provide it.
        "sleep_regularity":   True,
        "exercise_min_daily": True,
        "per_workout_hr_strength": True,
        # Thermal (sauna + cold exposure) is manual-/log-only, not
        # source-dependent. The capability is True everywhere; the coach
        # gates the report section on ``thermal_summary`` presence
        # (data-presence gating, like ``sleep_summary`` and ``swim_summary``).
        "thermal_log":        True,
        "light_therapy_log":  True,
    },
    "health_auto_export": {
        "hrv":                True,
        "wrist_temp":         True,
        "resting_hr_daily":   True,
        "walking_hr":         True,
        "sleep_stages":       True,
        "sleep_breath_dist":  True,
        "sleep_nights":       True,
        "sleep_regularity":   False,  # see note on xml: no segment-level timestamps
        "exercise_min_daily": True,
        "per_workout_hr_strength": True,
        "thermal_log":        True,
        "light_therapy_log":  True,
    },
    "hl_export": {
        "hrv":                False,
        "wrist_temp":         False,
        "resting_hr_daily":   False,
        "walking_hr":         False,
        "sleep_stages":       False,
        "sleep_breath_dist":  False,
        "sleep_nights":       False,
        "sleep_regularity":   False,
        "exercise_min_daily": False,
        "per_workout_hr_strength": False,
        "thermal_log":        True,
        "light_therapy_log":  True,
    },
}

# Applied when the Profile sheet is missing or unset — treat the data as
# coming from XML so existing <Person> trackers (created before the Profile
# sheet existed) keep their full capability surface. New <OtherPerson> trackers
# get bootstrapped to ``health_auto_export`` by
# ``import_health_auto_export.py``.
DEFAULT_DATA_SOURCE = "xml"

# Deload marker now lives on the TOTAL row's Notes column (col 9). The
# marker text is canonical "Deload Workout"; matching is case-insensitive.
DELOAD_MARKER = "deload workout"
TOTAL_LABEL = "TOTAL"

# =============================================================================
# Volume landmarks — TWO tables and one conversion between them
# =============================================================================
#
# UNITS. This is the part that was silently wrong before 2026-08 and is
# the reason the table is now split in two.
#
#   * `RP_DIRECT_SET_LANDMARKS` is in Renaissance Periodization's own unit:
#     **direct hard sets per week**, i.e. sets whose PRIMARY target is that
#     muscle. RP counts a set of bench press toward chest and toward
#     nothing else.
#   * The tracker does not measure that. `strength.weekly_volume_per_muscle`
#     credits the primary muscle 1.0 and every listed synergist 0.5
#     (training-science §1; Pelland/Helms/Schoenfeld tested direct vs
#     fractional head-to-head and fractional won every comparison,
#     2xlog BF 9.48-45.96). So the tracker's unit is **fractional sets per
#     week** = direct + 0.5 x synergist.
#
# Those are different axes. Comparing a fractional measurement against a
# direct-set landmark understates every muscle that receives synergist
# credit: 6 credited triceps sets can be 0 curls plus 12 pressing sets,
# which is exactly the failure `render_validators.workout_arm_dose_warnings`
# was written to catch after the fact. The landmark, not the validator,
# is the right place to fix it.
#
# CONVERSION. Fractional volume decomposes additively:
#
#     Q_fractional = Q_direct + S
#
# where S is the synergist credit the muscle receives from the program's
# COMPOUND work. S is driven by compound volume, not by isolation volume,
# so it is an OFFSET, not a multiplier — scaling the landmark by the
# observed fractional/direct ratio would be wrong (it would make the
# requirement grow with the isolation work that is supposed to satisfy it).
# A threshold on the direct axis therefore maps to the fractional axis by
# a shift of origin, and the SAME shift applies to MV, MEV, MAV and MRV.
#
# PROVENANCE OF THE OFFSETS. `SYNERGIST_CREDIT_OFFSET` below was measured,
# not assumed: per-week synergist-only credit over a 26-week window across
# both live trackers (52 person-weeks), pooled, then floored to a whole
# set. Flooring is deliberate — an offset that is too large silently
# raises every MEV and manufactures below-MEV verdicts, so the estimator
# is biased low on purpose.
#
# LIMITS, stated rather than hidden:
#   * S depends on the program. When compound volume drops (as it does
#     when most muscles move to the `maintain` tier), the true S drops
#     with it and these offsets become slightly too high. Re-measure at
#     each block boundary.
#   * Three muscles cannot be restated honestly and are left at their
#     direct values with offset 0 — see the `# AMBIGUOUS` markers. A
#     fourth (`external_rotators`) IS measurable and is restated; what it
#     lacks is a way to HIT the resulting target — see `# UNHITTABLE`.
#
# Source of the direct numbers: current (2024-26) Renaissance
# Periodization muscle-by-muscle guides + Mike Israetel's published
# per-muscle videos, cross-referenced — where the source muscle was
# actually measured — against Schoenfeld 2017 (J Sports Sci,
# dose-response meta-analysis), Baz-Valle 2022 (J Human Kinetics
# systematic review), and Pelland/Helms/Schoenfeld 2025 meta-regression
# (Sports Medicine). Verified by full-text grep: none of the three
# contains a single abdominal outcome, so this cross-reference does NOT
# cover `core` — see the `core`-specific provenance comment below.
#
# Treat these as **practitioner heuristics**, not RCT-validated
# thresholds. The shape of the volume-response curve is well supported
# (monotonically increasing with diminishing returns); the exact
# landmark points are coaching observation + dose-response curves
# fitted to per-muscle context.
#
# Convention: MV = maintenance (preserves muscle), MEV = minimum
# effective (smallest dose that drives growth), MAV = maximum adaptive
# (upper end of the best-gains band), MRV = maximum recoverable
# (ceiling beyond which chronic recovery degrades). MAV upper bound
# and MRV lower bound *overlap by design* — the productive and
# pushing-limit bands shade into each other.
#
# Numbers refreshed 2026-05 from the current RP help-center per-muscle
# pages. Several values were revised down from the 2018-2020 RP
# guidance: chest MV, quads MRV (non-priority), hamstrings/glutes
# MV+MEV, front delts (RP now recommends ~no direct work for most
# lifters — pressing covers it), calves MRV; traps MAV/MRV revised up.
# external_rotators / adductors / neck have no published RP landmark; values
# are reasonable practitioner extrapolations and should be treated as such.
# core has a published RP landmark but NO intervention evidence of any kind —
# the meta-analyses cited above contain no abdominal outcomes. See §24.1.
RP_DIRECT_SET_LANDMARKS = {
    "chest":        {"mv": 3,  "mev": 8,  "mav": 16, "mrv": 22},
    "back":         {"mv": 6,  "mev": 10, "mav": 18, "mrv": 25},
    "quads":        {"mv": 4,  "mev": 8,  "mav": 14, "mrv": 18},
    "hamstrings":   {"mv": 2,  "mev": 4,  "mav": 12, "mrv": 16},
    "glutes":       {"mv": 0,  "mev": 4,  "mav": 12, "mrv": 16},
    # front_delts is the THIRD MV == MEV collapse in this table, and the
    # only one the OFFSET creates rather than a published-range
    # correction: direct MV 0 / MEV 0 (RP recommends ~no direct front-delt
    # work — pressing covers it) both become 2 once the measured offset of
    # 2 is applied. So a muscle whose maintenance requirement was ZERO now
    # demands 2 fractional sets/wk, and `maintain` and `grow` target the
    # same number for it. Flagged, not adjusted: the collapse is what the
    # unit conversion honestly implies, since ~2 fractional sets/wk is
    # exactly what any pressing week already supplies, and front_delts is a
    # `maintain`-tier muscle whose target is therefore met by construction.
    # It becomes a real problem only if front_delts is ever nominated
    # `grow`, which would ask for MEV and be satisfied by doing nothing.
    "front_delts":  {"mv": 0,  "mev": 0,  "mav": 6,  "mrv": 12},
    "side_delts":   {"mv": 6,  "mev": 8,  "mav": 16, "mrv": 22},
    # rear_delts MEV was 8. RP's current published rear-delt range tops out
    # at 6 for MEV; 8 sat above their own band with no source. Lowered
    # 2026-08-02 (D9). MV is left at 6 and now EQUALS MEV, which collapses
    # the maintain/grow distinction for this muscle — flagged rather than
    # silently adjusted, because lowering MV was not authorised. rear_delts
    # is an `emphasis` muscle this block, so nothing reads its MV today.
    "rear_delts":   {"mv": 6,  "mev": 6,  "mav": 16, "mrv": 22},
    "biceps":       {"mv": 5,  "mev": 8,  "mav": 16, "mrv": 22},
    "triceps":      {"mv": 4,  "mev": 6,  "mav": 12, "mrv": 16},
    # calves MEV was 8, likewise above RP's published range. Same MV == MEV
    # caveat as rear_delts, and likewise an `emphasis` muscle this block.
    "calves":       {"mv": 6,  "mev": 6,  "mav": 14, "mrv": 18},
    "forearms":     {"mv": 2,  "mev": 4,  "mav": 8,  "mrv": 12},
    # Core = the abdominal wall (rectus abdominis + obliques). NOT the spinal
    # erectors, which have their own landmark below and carry the compound
    # contribution (squat/deadlift abdominal EMG is null — see §24.5).
    # Values are RP's PUBLISHED STANDARD abs table (rpstrength.com, 2024-01-03):
    # MV 0-4, MEV 0-4, MAV 4-12, MRV 12-20. Prior values (mav 16, mrv 25) were
    # taken from RP's "Primary Priority" SPECIALIZATION columns (MAV*P 16-24,
    # MRV*P 24-32+) — i.e. volumes that assume every other muscle is being
    # de-prioritised. That is wrong as a default.
    # HONESTY: no published core landmark is derived from intervention data. No
    # study has manipulated weekly set volume for abdominal hypertrophy, and
    # Schoenfeld 2017 / Baz-Valle 2022 / Pelland 2025 contain ZERO abdominal
    # outcomes (verified by full-text grep) — they do NOT source this row.
    # RP self-describes its landmarks as "averages based on our experience...
    # not dogmatic scriptures". Treat as practitioner heuristic; see §24.1.
    #   MV  = 0  — RP standard 0-4, bottom. Supported indirectly by Belavý
    #              2017 + PMID 21472438. Evidence tier: Moderate, conditional
    #              on doing compound work.
    #   MEV = 4  — RP standard 0-4; 4 is the top — conservative, won't
    #              under-prescribe. Evidence tier: Thin — no ab RCT supports
    #              any set count.
    #   MAV = 12 — RP standard MAV is 4-12; also the floor of Baz-Valle's
    #              12-20 limb optimum — the most defensible convergence
    #              point. Evidence tier: Thin.
    #   MRV = 20 — RP standard MRV is 12-20. Evidence tier: Thin.
    "core":         {"mv": 0,  "mev": 4,  "mav": 12, "mrv": 20},
    "erectors":     {"mv": 2,  "mev": 4,  "mav": 10, "mrv": 16},
    "traps":        {"mv": 2,  "mev": 4,  "mav": 15, "mrv": 22},
    # No published RP landmark — practitioner extrapolation:
    "external_rotators": {"mv": 0,  "mev": 2,  "mav": 6,  "mrv": 12},
    "adductors":    {"mv": 0,  "mev": 2,  "mav": 8,  "mrv": 12},
    "neck":         {"mv": 0,  "mev": 2,  "mav": 6,  "mrv": 12},
}

# The raw measurement behind the offsets, as DATA rather than as a
# comment: per-week synergist-only credit over 26 weeks x 2 trackers
# (52 person-weeks), pooled. `(pooled_median, pooled_mean)`.
#
# THE DERIVATION RULE, written down because the numbers do not imply it
# and because the two estimators disagree for two of the six rows:
#
#     offset = floor(min(pooled_median, pooled_mean))
#
# The SMALLER estimator wins, and only then is it floored. Both halves
# are the same bias: an offset that is too large silently raises every
# landmark and manufactures below-MEV verdicts, so the estimator is
# deliberately biased low (see LIMITS above). Using the median alone
# would hand `front_delts` and `glutes` an offset of 3 instead of 2 —
# those are the two rows where `floor(median) != floor(mean)`, and they
# are exactly the rows where a 26-week median lands on a round number
# while the mean records the weeks the pattern was absent.
#
# `SYNERGIST_CREDIT_OFFSET` is derived from this table, so the published
# estimate and the applied integer cannot drift apart. `test_w4_specs.py`
# pins the rule, the resulting integers, AND the derived
# `VOLUME_LANDMARKS` values every consumer actually reads — a bare
# `landmarks == published + offset` assertion is true for any offset at
# all and did not notice when the biceps offset was mutated 3 -> 6
# (which moved its MEV 11 -> 14 with the whole suite green).
SYNERGIST_CREDIT_MEASUREMENT = {
    #                     pooled median, pooled mean   -> offset
    "biceps":            (3.00, 3.00),               # -> 3
    "triceps":           (3.50, 3.45),               # -> 3
    "front_delts":       (3.00, 2.48),               # -> 2
    "glutes":            (3.00, 2.76),               # -> 2
    "rear_delts":        (1.50, 1.58),               # -> 1
    "external_rotators": (1.00, 1.05),               # -> 1, see UNHITTABLE
}

# Weekly synergist credit (0.5 per synergist tag) a muscle receives from
# the compound work in the reference program. Adding this to a direct-set
# landmark converts it to the tracker's fractional unit. See the block
# comment above for method; see `tests/test_w4_specs.py` for the
# assertions that keep the two tables consistent and that check every
# offset against the catalog's own synergist tags.
#
# Everything omitted from this table has offset 0. For nine of them that
# is STRUCTURAL, not an estimate: adductors, calves, core, neck and
# side_delts appear zero times as a synergist anywhere in
# `exercises-database.md`, and back / chest / quads / hamstrings appear so
# rarely that 26 weeks of real logs measured a fractional/direct ratio of
# 1.00-1.01. For those muscles the two units are the same unit and the
# published landmark transfers unchanged. `core` being in that list is the
# load-bearing case: no catalog entry credits core as a synergist (squat
# and deadlift abdominal EMG is null, §24.5), so the core landmark needs
# no restatement at all.
#
# AMBIGUOUS — deliberately left at 0 rather than guessed. The marker
# means ONE thing: the number is not known. Keeping it to that one
# meaning is what makes the three remaining markers worth reading.
#   erectors            0 primary entries logged in either program; ALL of
#                       the measured credit is synergist. The two trackers
#                       disagree completely (one hinges, one does not:
#                       median 3.0/wk vs 0.0/wk) — a program difference,
#                       not noise, so the pooled median of 0 is not
#                       meaningful either. Whether RP's erector MEV is
#                       meant to be satisfied by hinges is genuinely
#                       unsettled.
#   forearms            2 synergist entries (Suitcase Carry, Dumbbell
#                       Farmer Walk); neither has ever been logged, so the
#                       measurement is 0 by absence, not by structure. Will
#                       need re-measuring once carries enter the rotation.
#   neck                no data.
#
# UNHITTABLE — measured, restated, and knowingly out of reach:
#   external_rotators   pooled median 1.00, pooled mean 1.05, nonzero in
#                       BOTH trackers independently (Cable Face Pull is
#                       the crediting entry). The measurement is not
#                       ambiguous and it was mislabelled as such until
#                       2026-08-02. What is true is narrower: the catalog
#                       has ZERO primary entries for the muscle, so direct
#                       sets are not expressible in the current vocabulary
#                       and the restated MEV of 3 cannot be hit by any
#                       prescription this coach can write.
#
#                       Restated anyway, because SATISFIABILITY is not the
#                       question this table answers. The offset is a UNIT
#                       CONVERSION; withholding a measured conversion
#                       because the converted target is hard to hit
#                       conflates two concerns, and the conflation is not
#                       neutral — at offset 0 the muscle's ~1.05 fractional
#                       sets/wk were compared against a DIRECT-set MEV of
#                       2 and read as 52% of target, when the honest
#                       fractional comparison is 1.05 against 3, i.e. 35%.
#                       The old marker made the least-served muscle in the
#                       table read as the better-served one. An unhittable
#                       target that reads "you are not training this, and
#                       you cannot until the catalog gains a primary entry"
#                       is the accurate signal; the remedy is a catalog
#                       entry (external-rotation work exists — it is the
#                       vocabulary that is missing), not a softer landmark.
SYNERGIST_CREDIT_OFFSET = {
    # floor(min(median, mean)); both estimates are non-negative, so int()
    # IS floor here.
    muscle: int(min(median, mean))
    for muscle, (median, mean) in SYNERGIST_CREDIT_MEASUREMENT.items()
}

# The table every consumer reads. Unit: FRACTIONAL sets per week
# (direct + 0.5 x synergist) — the same unit
# `strength.weekly_volume_per_muscle` emits. Derived, not hand-maintained,
# so the published numbers and the unit conversion can never drift apart.
VOLUME_LANDMARKS = {
    muscle: {
        band: value + SYNERGIST_CREDIT_OFFSET.get(muscle, 0)
        for band, value in bands.items()
    }
    for muscle, bands in RP_DIRECT_SET_LANDMARKS.items()
}


# =============================================================================
# Priority tiers — emphasise / grow / maintain
# =============================================================================
#
# Chasing MEV on all 18 muscles at once routes meaningfully to none of
# them: the weekly set budget is finite, so a target every muscle shares
# is a target no muscle owns. RP's own guidance is a three-tier split, and
# this table is the machine-readable version of it.
#
#   emphasis  -> mid-MAV, i.e. the midpoint of [MEV, MAV]. The middle of
#                the productive band, not its ceiling: MAV is where returns
#                start costing more fatigue than they give back, so sitting
#                ON it for a whole block is a fatigue decision, not a
#                growth one.
#   grow      -> MEV. The smallest dose that still drives adaptation.
#   maintain  -> MV. Preserves the muscle while its budget goes elsewhere.
#
# `maintain` is the DEFAULT. A muscle that nobody nominated is not a
# muscle to grow; it is a muscle to hold. That default is the whole point
# of the tier model — without it the table would degrade back into "grow
# everything".
PRIORITY_TIER_BAND = {
    "emphasis": "mid_mav",
    "grow":     "mev",
    "maintain": "mv",
}
PRIORITY_TIERS = tuple(PRIORITY_TIER_BAND)
DEFAULT_PRIORITY_TIER = "maintain"

# `profile.csv` key carrying the per-person override. Value format is a
# semicolon-separated list of `muscle:tier` pairs, e.g.
#   muscle_priority_tiers,core:emphasis;side_delts:emphasis;biceps:grow
# Unlisted muscles fall to DEFAULT_PRIORITY_TIER. Unknown muscle names and
# unknown tier names are ignored (a typo must not silently retier a muscle);
# `muscle_priority_tiers` reports them via its `unknown` return.
MUSCLE_PRIORITY_PROFILE_KEY = "muscle_priority_tiers"

# Fallback used when `profile.csv` carries no override. This is the
# 2026-08-02 block's emphasis set (D8), not a permanent property of the
# system: core because 6 months of logs are 94% spinal flexion; side and
# rear delts, calves and traps because they are the muscles the current
# split under-serves. Biceps and triceps were considered and dropped —
# both already sit at or above MEV.
#
# The accepted trade: chest, back, quads, hamstrings and glutes run at
# MAINTENANCE this block. Bench and squat volume goes down. That is the
# cost of emphasising anything at all.
BLOCK_EMPHASIS_DEFAULT = (
    "core", "side_delts", "rear_delts", "calves", "traps",
)


# =============================================================================
# Prescription specs — distribution-shaped weekly targets
# =============================================================================
#
# WHY THESE HAVE THREE AXES AND NOT ONE.
#
# The 2026-07 fix made per-week core SET COUNT the enforced target. The
# next generated plan met it with `Ab Crunch Machine x2 sets x4 sessions`:
# target satisfied, training goal not. Measured outcome over the following
# six months — 94% of all core work spinal or hip flexion, anti-rotation 0
# sets, loaded carry 0 sets, anti-lateral-flexion 1 set.
#
# The lesson generalises past core: this coach optimises precisely to what
# is measured and stops there, so a target with only a QUANTITY axis is
# always satisfiable by the cheapest legal item x N. Every spec below
# therefore carries three machine-checkable axes:
#
#   quantity   how much   (sets per session / per week)
#   diversity  how spread (distinct exercises, distinct pattern categories)
#   identity   which      (a required category; a per-exercise frequency cap)
#
# Drop any one axis and a degenerate solution reappears. Drop diversity and
# you get one exercise x N. Drop identity and you get three flavours of the
# same movement. Drop quantity and you get one token set of each.
CORE_WEEK_SPEC = {
    # QUANTITY. Per session, keyed by session type (D3). Lower days carry
    # the bigger share because they have the isolation slots to spare.
    "sets_per_session": {"lower": 4, "upper": 2},
    # A third set on an upper day is not a training problem; a fifth is.
    # Under-dosing is never tolerated - that is the failure being fixed.
    "session_set_overshoot_tolerance": 1,
    # DIVERSITY.
    "min_distinct_exercises_per_week": 3,
    "min_pattern_categories_per_week": 3,
    # IDENTITY. Pattern categories are the CORE subsections in
    # `exercises-database.md` (Flexion / Anti-Extension / Anti-Rotation /
    # Anti-Lateral-Flexion / Rotation) - read from the catalog, never
    # duplicated here.
    "max_sessions_per_exercise_per_week": 2,
    "min_loaded_flexion_exercises_per_week": 1,
    "flexion_category": "flexion",
    # QUANTITY again, but on the PATTERN rather than on the total — and
    # the two flexion keys are different constraints, not a duplicate.
    # `min_loaded_flexion_exercises_per_week` counts EXERCISES, so one
    # bullet carrying one set satisfies it in full. Measured exploit
    # (2026-08-02): a four-session week of 8 core sets carrying a SINGLE
    # flexion set (12.5%) and 70 seconds of bodyweight holds cleared every
    # axis in this file and rendered at exit 0. Flexion set count was the
    # one thing the 2026-08 rebuild left unmeasured when it replaced a
    # scalar set target with distribution-shaped ones, and §5.2 of the
    # spec says in advance what happens to anything unmeasured.
    #
    # WHY A THIRD. §4.2's rotation pool is two slots per session — slot A
    # loaded flexion, slot B rotating non-flexion — so the structure the
    # coach is instructed to follow already implies ~50% flexion. The
    # floor is set deliberately BELOW that, because the pool is a default
    # and a week that legitimately spends an extra slot on anti-rotation
    # or a carry has to stay authorable. A third is the largest share that
    # never contradicts the pool, and it is the point below which flexion
    # stops being a pattern the week trains and becomes a token it names.
    #
    # WHY ALSO AN ABSOLUTE THREE. A share alone is scale-free: at 3 core
    # sets a third is 1 set, and one set of anything is a rehearsal (the
    # same judgement as `MIN_SETS_PER_DISTINCT_EXERCISE` = 2). Three is
    # the smallest count that is a real dose plus evidence of intent, and
    # it sits just under RP's published core MEV of 4 direct sets —
    # under, on purpose, because a floor must not read as the target.
    #
    # This is a FLOOR, not a band. Nothing here caps flexion; that is
    # `min_pattern_categories_per_week`'s job. The failure being fixed is
    # 12%, and the failure before it was 94%, so both ends need an axis
    # and they are different axes.
    "min_flexion_share_of_core_sets": 1 / 3,
    "min_flexion_sets_per_week": 3,
}

# Same shape, one muscle each side of the elbow. The >=6 direct sets/week
# floor is unchanged; the distinct-exercise axis is new and exists for the
# same reason core's does - 6 sets of one pushdown is a quantity target met
# and a training target missed.
ARM_WEEK_SPEC = {
    "min_direct_sets_per_week": 6,
    "min_distinct_exercises_per_week": 2,
}


# =============================================================================
# Dose progression — the spec for "is this the same plan again?"
# =============================================================================
#
# The complaint the whole workstream started from was "every plan is the
# same plan", and until 2026-08 nothing checked it: `dose_staleness` was
# computed into the payload for the coach to READ and no validator looked
# at it, so a coach could re-prescribe every load and rep target
# identically and render clean. The three axes above stop a plan being
# degenerate WITHIN one week; this one stops it being degenerate ACROSS
# weeks, which is a different failure and was the one the user actually
# reported.
#
# What "carried forward" and "moved" mean is NOT defined here. Both live
# in `adherence` — `dose_staleness` decides which exercises count as
# carried, and `_dose_delta` decides whether a change is material (2% of
# load, one whole rep of range midpoint, or a set count). Restating either
# would give the payload's report and the gate two different definitions
# of the same word, and they would drift.
DOSE_PROGRESSION_SPEC = {
    # SKILL.md's own stated target, and the same number
    # `adherence.dose_staleness` reports as ``target_max_pct``. The
    # measured baseline was 70% of carried exercises returning with an
    # unchanged dose. A test pins these two equal; they are one number
    # seen from the report side and the gate side.
    "max_unchanged_share": 0.40,
    # Below this many carried exercises the share is noise, not a
    # measurement: at 3 carried lifts one re-copy is already 33% and two
    # is 67%, so the check would fire on the arithmetic rather than on the
    # behaviour. Deload and comeback weeks are exactly where the carried
    # count collapses, and they are the weeks least deserving of a
    # spurious block. The real corpus runs 11-22 carried in a normal week.
    "min_carried_for_share": 5,
}

# Canonicalise the muscle tokens that appear in exercises-database.md to the
# snake_case keys used everywhere else (and in VOLUME_LANDMARKS).
MUSCLE_ALIASES = {
    "chest": "chest", "upper chest": "chest",
    "back": "back", "lats": "back",  # lats folded into back (no separate landmark)
    "biceps": "biceps", "triceps": "triceps",
    "quads": "quads", "hamstrings": "hamstrings",
    "glutes": "glutes", "adductors": "adductors",
    "calves": "calves", "forearms": "forearms",
    "abs": "core", "core": "core",   # abs folded into core (no separate landmark)
    "erectors": "erectors", "traps": "traps",
    "neck": "neck",
    "front delt": "front_delts", "front delts": "front_delts",
    "side delt": "side_delts",  "side delts":  "side_delts",
    "rear delt": "rear_delts",  "rear delts":  "rear_delts",
    "external rotators": "external_rotators",
    "shoulders": None,          "full body": None,
    "posterior chain": "glutes",  # broad token — primary driver is glutes
}

# Which ## SECTION header implies which primary muscle. None means "use
# subsection hint or parenthetical override". SHOULDERS is deliberately None
# because its subsections route to specific delt regions.
SECTION_PRIMARY = {
    "WARMUP": None, "CARDIO": None, "FULL BODY": None, "FULL BODY (COMPOUND)": None,
    "CHEST": "chest", "BACK": "back",
    "SHOULDERS": None,
    "BICEPS": "biceps", "TRICEPS": "triceps",
    "QUADS": "quads", "HAMSTRINGS": "hamstrings",
    "GLUTES": "glutes", "ADDUCTORS": "adductors",
    "CALVES": "calves", "CORE": "core",
    "NECK": "neck",
}

# Subsection hints that override the section heading (used inside SHOULDERS
# and for the stray "Forearms" subsection under BICEPS). Matched by substring
# against the lowercased subsection header.
SUBSECTION_PRIMARY_HINTS = [
    ("lateral delt", "side_delts"),
    ("rear delt",    "rear_delts"),
    ("vertical push","front_delts"),  # overhead press etc. primarily hit front delts
    ("traps",        "traps"),
    ("forearms",     "forearms"),
]

# =============================================================================
# Longevity dashboard norm tables (Trajectory tab)
# =============================================================================
#
# Single source of truth for the "where should I be?" question every metric
# on the Trajectory tab has to answer. Each table maps an age band to
# population norms (Cooper/ACSM, NHANES, Whoop/Oura/Empirical Health) and a
# longevity target (Attia "elite-for-a-decade-younger" where defined,
# otherwise the top research band).
#
# Convention: tables are keyed by sex then by (age_lo, age_hi) inclusive.
# Helpers downstream resolve the right band from a person's DOB + the
# current date; never freeze "age 28" anywhere.

# Cooper Institute / ACSM VO2 max norms (ml/kg/min). Each band has p50
# (median), p75 ("above average"), p95 ("elite"), and the Attia longevity
# target (top of the next-younger-decade elite band). Source: Cooper
# Institute Aerobic Fitness Norms + Attia AMA #80.
VO2MAX_NORMS = {
    "male": {
        (20, 29): {"p50": 48.0, "p75": 51.0, "p95": 55.4, "longevity": 60.0},
        (30, 39): {"p50": 44.0, "p75": 47.5, "p95": 52.5, "longevity": 56.0},
        (40, 49): {"p50": 40.5, "p75": 44.0, "p95": 49.0, "longevity": 53.0},
        (50, 59): {"p50": 36.5, "p75": 40.0, "p95": 45.5, "longevity": 50.0},
        (60, 69): {"p50": 32.5, "p75": 36.0, "p95": 41.5, "longevity": 46.0},
    },
    "female": {
        (20, 29): {"p50": 36.5, "p75": 40.0, "p95": 45.0, "longevity": 49.0},
        (30, 39): {"p50": 34.5, "p75": 37.5, "p95": 42.5, "longevity": 46.0},
        (40, 49): {"p50": 32.5, "p75": 35.5, "p95": 40.0, "longevity": 43.0},
        (50, 59): {"p50": 29.5, "p75": 32.5, "p95": 37.5, "longevity": 40.0},
        (60, 69): {"p50": 26.5, "p75": 29.5, "p95": 34.5, "longevity": 37.0},
    },
}

# Apple Watch HRV (SDNN) cohort bands (ms). Sources: Empirical Health
# (Apple Watch cohort), MyHRV by-age tables. SDNN is NOT comparable to
# RMSSD (Whoop/Oura) — the dashboard labels units explicitly so a user
# never compares Apple SDNN against a Whoop number.
HRV_SDNN_NORMS = {
    "male": {
        (20, 29): {"p50": 42.0, "good": 55.0, "elite": 70.0},
        (30, 39): {"p50": 38.0, "good": 50.0, "elite": 65.0},
        (40, 49): {"p50": 32.0, "good": 45.0, "elite": 60.0},
        (50, 59): {"p50": 28.0, "good": 40.0, "elite": 55.0},
        (60, 69): {"p50": 25.0, "good": 35.0, "elite": 50.0},
    },
    "female": {
        (20, 29): {"p50": 40.0, "good": 52.0, "elite": 65.0},
        (30, 39): {"p50": 35.0, "good": 47.0, "elite": 60.0},
        (40, 49): {"p50": 30.0, "good": 42.0, "elite": 55.0},
        (50, 59): {"p50": 26.0, "good": 37.0, "elite": 50.0},
        (60, 69): {"p50": 23.0, "good": 32.0, "elite": 45.0},
    },
}

# Resting Heart Rate bands (bpm). AHA general adult range plus Copenhagen
# Male Study mortality cutoffs. Lower-is-better — "longevity" is the
# trained-endurance target, not the floor of healthy.
RHR_NORMS = {
    "male": {
        "p50": 70.0, "good": 60.0, "elite": 50.0, "longevity": 50.0,
        "warn_above": 90.0,  # Copenhagen Male Study: 3x mortality vs <80
    },
    "female": {
        "p50": 74.0, "good": 64.0, "elite": 54.0, "longevity": 54.0,
        "warn_above": 90.0,
    },
}

# Heart-Rate Recovery 1-minute (bpm drop). Cole 1999 NEJM cutoff for
# autonomic dysfunction is <12 bpm; meta-analysis: attenuated HRR =
# +69% CV events / +68% all-cause mortality.
HRR_1MIN_NORMS = {
    "abnormal_below": 12.0,
    "borderline":     15.0,
    "normal":         25.0,
    "excellent":      35.0,
}

# Sleep architecture targets (healthy adult, NSF + Ohayon meta-analysis).
SLEEP_TARGETS = {
    "total_h_min":             7.0,
    "total_h_target":          8.0,
    "deep_pct_min":            13.0,
    "deep_pct_max":            23.0,
    "rem_pct_min":             20.0,
    "rem_pct_max":             25.0,
    "deep_plus_rem_h_target":  2.5,
    "efficiency_pct_healthy":  85.0,
    "efficiency_pct_disturbed": 80.0,
    "resp_rate_min":           12.0,
    "resp_rate_max":           20.0,
    # Sleep Regularity Index (Phillips 2017 / Windred 2024). 100 = identical
    # sleep schedule every day. UK Biobank top quintile (n=60,977) =
    # 20-48% lower all-cause mortality vs bottom quintile. SRI is a stronger
    # mortality predictor than duration.
    "sri_top_quintile":        87.0,   # UK Biobank top-quintile cutoff
    "sri_bottom_quintile":     71.0,   # UK Biobank bottom-quintile cutoff
    "sri_target":              90.0,
}

# Body composition targets (DEXA-based per Attia). VAT / ALMI / BMD numbers
# only resolve once a DEXA scan is on file; for now BF% and bodyweight
# trend are the live signals.
BODY_COMP_TARGETS = {
    "male": {
        "bf_pct_healthy_max":    20.0,
        "bf_pct_elite":          15.0,
        "bf_pct_longevity":      12.0,
        "vat_cm2_optimal_max":   100.0,
        "vat_cm2_elite_max":     80.0,
        "waist_cm_healthy_max":  90.0,
        "almi_p75_target":       True,
    },
    "female": {
        "bf_pct_healthy_max":    28.0,
        "bf_pct_elite":          22.0,
        "bf_pct_longevity":      18.0,
        "vat_cm2_optimal_max":   80.0,
        "vat_cm2_elite_max":     60.0,
        "waist_cm_healthy_max":  80.0,
        "almi_p75_target":       True,
    },
}

# Training-load Acute:Chronic Workload Ratio sweet spot (Gabbett 2016 BJSM).
# Injured athletes hit 0.8-1.3 only 37.5% of time vs 75% for non-injured.
ACWR_BANDS = {
    "detraining_below": 0.8,
    "sweet_spot_lo":    0.8,
    "sweet_spot_hi":    1.3,
    "caution_hi":       1.5,
    "injury_risk_above": 1.5,
}

# Daily step thresholds (Paluch 2022 Lancet Public Health; Saint-Maurice
# 2023 JAMA Netw Open). 8k/day is the under-60 mortality-plateau target.
STEP_TARGETS = {
    "threshold_daily":       8000,
    "days_per_week_target":  5,
    "mortality_floor":       4000,
    "diminishing_returns":   12000,
}

# Zone 2 weekly target (San-Millán/Attia podcast #201). 150-200 min/wk
# is the Attia prescription; Norwegian 4x4 adds 1 VO2-max session.
Z2_TARGETS = {
    "min_per_week_floor":   150,
    "min_per_week_target":  200,
    "vo2_sessions_per_week": 1,   # Norwegian 4x4
}

# Longevity Score composite weights (Trajectory headline). Weights are
# normalized at runtime to whatever subset of inputs is actually present
# (mirrors recovery_score's renormalization). No weight ≥ 0.30 — the
# headline should never live or die on a single signal.
LONGEVITY_SCORE_WEIGHTS = {
    "vo2_percentile":         0.25,   # cardiorespiratory headline
    "hrv_trend":              0.10,   # autonomic
    "rhr_trend":              0.05,   # cardio fitness proxy
    "sleep_regularity":       0.15,   # consistency, mortality-relevant
    "sleep_quality":          0.10,   # duration × deep+REM × efficiency
    "training_load_in_band":  0.10,   # ACWR sweet-spot adherence
    "z2_weekly_adherence":    0.05,   # cardio base
    "body_comp_trend":        0.05,   # bodyweight directional vs goal
    "behavioral_consistency": 0.10,   # days ≥8k steps + workout adherence
    "strength_progression":   0.05,   # mean e1RM slope direction
}

# Per-metric timeframe rules (single source of truth for "what window
# does each metric use?"). The renderer reads this to label each card
# without hardcoding window strings; downstream compute functions
# already use these intervals.
METRIC_WINDOWS = {
    # Fast physiology
    "hrv_sdnn":         {"latest": "7d",  "trend": "7d",  "baseline": "60d"},
    "resting_hr":       {"latest": "7d",  "trend": "7d",  "baseline": "60d"},
    "wrist_temp_c":     {"latest": "3d",  "trend": "7d",  "baseline": "60d"},
    "sleep_total_h":    {"latest": "7d",  "trend": "7d",  "baseline": "28d"},
    # Slow physiology
    "vo2max":           {"latest": "28d", "trend": "90d", "baseline": "lifetime"},
    "bodyweight_kg":    {"latest": "7d",  "trend": "28d", "baseline": "lifetime"},
    # Recovery / training load
    "hr_recovery_1min": {"latest": "5d",  "trend": "28d", "baseline": "60d"},
    "acwr":             {"latest": "today", "trend": "7d", "baseline": "28d"},
    "tsb":              {"latest": "today", "trend": "7d", "baseline": "42d"},
    # Behavioral / regularity
    "sri":              {"latest": "14d", "trend": "28d", "baseline": "14d"},
    "steps_threshold":  {"latest": "7d",  "trend": "28d", "baseline": "weekly"},
    "z2_minutes":       {"latest": "7d",  "trend": "28d", "baseline": "weekly"},
}


# =============================================================================
# Recovery-gate (5-tier session recommendation) thresholds
# =============================================================================
#
# Single source of truth for the gate that decides "rest / Zone 2 / modified
# strength / normal strength" before any workout markdown is generated.
#
# Sources:
# - Tier A (illness): Cole 1999 NEJM (autonomic crash mortality), TrainingPeaks
#   "4 signs of overtraining", Oura pre-illness wrist temp deviation band.
# - Tier B (reactive deload): TrainingPeaks PMC bands (TSB), Altini HRV4Training
#   (baseline-below-band heuristic), Israetel RP MRV-breach protocol, Tuchscherer
#   / Helms reactive-deload trigger, Impellizzeri 2020 IJSPP (10% rule survives).
# - Tier C (downgrade): Stronger by Science autoregulation, Saw 2016 BJSM.
# - Tier E (over-recovered taper): TrainingPeaks form-band guidance.
#
# Thresholds are tightened against the tracker's TSB scale (which runs narrower
# than TrainingPeaks' classic ±30 because our TRIMP is shorter-window).

SESSION_GATE_THRESHOLDS = {
    # ---- Tier A: illness / acute rest (refuse strength flat-out) ----
    "tier_a_wrist_temp_dev_c":         0.7,    # Oura pre-illness deviation
    "tier_a_hrv_z_paired_with_temp":  -1.0,    # autonomic suppression alongside temp rise
    "tier_a_rhr_dev_bpm":              10.0,   # +10 bpm sustained = serious
    "tier_a_rhr_sustained_days":       3,
    "tier_a_recovery_score_crash":     3.0,    # composite crash
    "tier_a_hrv_z_crash":             -1.5,    # paired with recovery crash
    "tier_a_rhr_z_crash":              1.0,    # paired with recovery crash

    # ---- Tier B: reactive deload (refuse planned strength, substitute) ----
    "tier_b_tsb_high_fatigue":        -15.0,   # SKILL.md existing band
    "tier_b_hrv_z_sustained":         -0.75,   # Altini baseline-below-band
    "tier_b_muscles_over_mrv_count":   3,      # RP MRV-breach protocol
    "tier_b_wow_spike_pct":            60.0,   # 10% rule (10% green, >60% red)
    # Absolute acute-load floor for the WoW spike. A big week-over-week
    # percent off a near-zero base (e.g. one short HIIT after a quiet week)
    # is an artifact of a tiny denominator, not accumulated fatigue — the
    # all-modality TRIMP feeding wow is noisy over a small base while the
    # gate's TSB is strength-scoped. The spike only fires when corroborated:
    # negative strength freshness AND acute 7-day TRIMP above this floor, so
    # a strength-fresh athlete isn't pinned in deload by a cardio blip. This
    # mirrors the corroboration the soft Tier-C triggers already require.
    "tier_b_wow_acute_load_floor":     300.0,  # min acute 7d TRIMP to corroborate
    "tier_b_stalled_lifts_count":      4,      # Tuchscherer reactive-deload; broad program-wide ceiling-stall (corroborated by fatigue), not 2 flat isolations

    # ---- Tier C: downgrade (modified strength is fine) ----
    "tier_c_recovery_score_lo":        3.0,
    "tier_c_recovery_score_hi":        5.0,
    "tier_c_hrv_z_lo":                -0.75,
    "tier_c_hrv_z_hi":                -0.30,
    "tier_c_sleep_total_h_floor":      5.0,    # last night
    "tier_c_sleep_7d_mean_floor":      6.0,
    "tier_c_sri_floor":                71.0,   # UK Biobank bottom quintile
    "tier_c_rhr_z_floor":              0.50,
    "tier_c_muscles_over_mrv_count":   1,
    "tier_c_downgrade_volume_pct":     25.0,   # -25% volume on secondaries
    # Corroboration guard for the SOFT recovery/HRV Tier-C triggers. HRV is
    # the dominant input to recovery_score, so "moderate recovery" and
    # "mildly-low HRV" are the SAME signal, not two. A single soft dip
    # should not cut training volume while the athlete is fresh. So the
    # soft band only downgrades when recovery is genuinely low (below the
    # hard floor) OR freshness is actually negative (under real load). This
    # mirrors the corroboration the HR-creep and stalled-lift triggers
    # already require. A genuinely low score (< hard floor) still fires alone.
    "tier_c_recovery_hard_floor":      4.0,    # below this = real, fires alone
    "tier_c_soft_tsb_floor":          -5.0,    # strength TSB < this = under load (carrying-load band); soft dip then corroborated

    # ---- Tier D: green (default — train as planned) ----
    "tier_d_recovery_score_min":       5.5,
    "tier_d_tsb_lo":                  -10.0,
    "tier_d_tsb_hi":                   0.0,

    # ---- Tier E: over-recovered / taper warning ----
    "tier_e_tsb_high":                 10.0,
}


def muscle_priority_tiers(profile: dict | None = None) -> tuple[dict, list[str]]:
    """Resolve every muscle to an ``emphasis`` / ``grow`` / ``maintain`` tier.

    Returns ``(tiers, unknown_tokens)``. ``tiers`` covers every key in
    ``VOLUME_LANDMARKS``; ``unknown_tokens`` lists the ``muscle:tier``
    pairs that were dropped so the caller can surface a typo instead of
    silently applying the default.

    ``profile`` is the ``profile.csv`` dict from
    ``shared.csv_store_profile.read_profile``. The override lives under
    ``MUSCLE_PRIORITY_PROFILE_KEY``; when it is absent the
    ``BLOCK_EMPHASIS_DEFAULT`` set is applied and everything else falls to
    ``DEFAULT_PRIORITY_TIER``. Config wins over the default in full — a
    profile that names an emphasis set replaces the built-in one rather
    than adding to it, so a person can drop core from emphasis without
    editing code.
    """
    tiers = {m: DEFAULT_PRIORITY_TIER for m in VOLUME_LANDMARKS}
    unknown: list[str] = []

    raw = (profile or {}).get(MUSCLE_PRIORITY_PROFILE_KEY)
    raw = raw.strip() if isinstance(raw, str) else ""
    if not raw:
        for muscle in BLOCK_EMPHASIS_DEFAULT:
            tiers[muscle] = "emphasis"
        return tiers, unknown

    for pair in raw.replace(",", ";").split(";"):
        pair = pair.strip()
        if not pair:
            continue
        muscle, _, tier = pair.partition(":")
        muscle = muscle.strip().lower().replace(" ", "_")
        tier = tier.strip().lower()
        if muscle in tiers and tier in PRIORITY_TIER_BAND:
            tiers[muscle] = tier
        else:
            unknown.append(pair)
    return tiers, unknown


def muscle_volume_targets(tiers: dict | None = None,
                          landmarks: dict | None = None) -> dict:
    """Per-muscle weekly set target implied by its priority tier.

    ``{muscle: {"tier": str, "band": str, "target_sets": float}}``, in the
    same FRACTIONAL unit as ``VOLUME_LANDMARKS`` and
    ``strength.weekly_volume_per_muscle`` — see the units note above the
    landmark tables. ``mid_mav`` is the midpoint of ``[mev, mav]``.
    """
    if tiers is None:
        tiers, _ = muscle_priority_tiers()
    marks = landmarks if landmarks is not None else VOLUME_LANDMARKS

    out: dict = {}
    for muscle, bands in marks.items():
        tier = tiers.get(muscle, DEFAULT_PRIORITY_TIER)
        band = PRIORITY_TIER_BAND.get(tier, PRIORITY_TIER_BAND[DEFAULT_PRIORITY_TIER])
        if band == "mid_mav":
            target = (bands["mev"] + bands["mav"]) / 2.0
        else:
            target = float(bands[band])
        out[muscle] = {"tier": tier, "band": band,
                       "target_sets": round(target, 1)}
    return out


def age_band(norms_table: dict, sex: str, age: int) -> dict | None:
    """Resolve (sex, age) to a norm-band dict from one of the per-sex tables
    above. Returns ``None`` when sex or age is missing/out-of-range — the
    renderer then degrades to "cohort norms unavailable".
    """
    if not sex or age is None:
        return None
    sex_key = sex.lower()
    table = norms_table.get(sex_key)
    if not table:
        return None
    for (lo, hi), bands in table.items():
        if lo <= age <= hi:
            return bands
    return None
