"""Constants and capability tables for the /coach read pipeline.

Pure data — no functions. Everything here is module-level so it can be
imported once and referenced cheaply from every analytics module.

Three groups:

- **Source capabilities**: per-data-source feature map
  (``SOURCE_CAPABILITIES``) plus the ``DEFAULT_DATA_SOURCE`` fallback for
  legacy trackers without a Profile sheet.
- **Sheet conventions**: ``MONTHLY_RE`` (the YYYY.MM sheet-name regex),
  ``DELOAD_MARKER`` (case-insensitive substring on TOTAL-row Notes),
  ``EMPTY_STREAK_STOP`` (max consecutive blank rows scanned), and
  ``TOTAL_LABEL`` (the canonical TOTAL-row exercise sentinel).
- **Volume + muscle taxonomy**: ``VOLUME_LANDMARKS`` (per-muscle MV/MEV/
  MAV/MRV bands), ``MUSCLE_ALIASES`` (database-token → snake_case key),
  ``SECTION_PRIMARY`` (## SECTION header → primary muscle), and
  ``SUBSECTION_PRIMARY_HINTS`` (subsection-substring overrides).
"""
from __future__ import annotations

import re

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
# coming from XML so existing Nihad trackers (created before the Profile
# sheet existed) keep their full capability surface. New Fabian trackers
# get bootstrapped to ``health_auto_export`` by
# ``import_health_auto_export.py``.
DEFAULT_DATA_SOURCE = "xml"

MONTHLY_RE = re.compile(r"^\d{4}\.\d{2}$")
# Deload marker now lives on the TOTAL row's Notes column (col 9). The
# marker text is canonical "Deload Workout"; matching is case-insensitive.
DELOAD_MARKER = "deload workout"
EMPTY_STREAK_STOP = 10
TOTAL_LABEL = "TOTAL"

# Per-muscle weekly volume landmarks (hard sets). Source: current
# (2024-26) Renaissance Periodization muscle-by-muscle guides + Mike
# Israetel's published per-muscle videos, cross-referenced against
# Schoenfeld 2017 (J Sports Sci, dose-response meta-analysis),
# Baz-Valle 2022 (J Human Kinetics systematic review), and
# Pelland/Helms/Schoenfeld 2025 meta-regression (Sports Medicine).
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
# external_rotators / adductors have no published RP landmark; values
# are reasonable practitioner extrapolations and should be treated
# as such.
VOLUME_LANDMARKS = {
    "chest":        {"mv": 3,  "mev": 8,  "mav": 16, "mrv": 22},
    "back":         {"mv": 6,  "mev": 10, "mav": 18, "mrv": 25},
    "lats":         {"mv": 6,  "mev": 10, "mav": 18, "mrv": 25},
    "quads":        {"mv": 4,  "mev": 8,  "mav": 14, "mrv": 18},
    "hamstrings":   {"mv": 2,  "mev": 4,  "mav": 12, "mrv": 16},
    "glutes":       {"mv": 0,  "mev": 4,  "mav": 12, "mrv": 16},
    "front_delts":  {"mv": 0,  "mev": 0,  "mav": 6,  "mrv": 12},
    "side_delts":   {"mv": 6,  "mev": 8,  "mav": 16, "mrv": 22},
    "rear_delts":   {"mv": 6,  "mev": 8,  "mav": 16, "mrv": 22},
    "biceps":       {"mv": 5,  "mev": 8,  "mav": 16, "mrv": 22},
    "triceps":      {"mv": 4,  "mev": 6,  "mav": 12, "mrv": 16},
    "calves":       {"mv": 6,  "mev": 8,  "mav": 14, "mrv": 18},
    "forearms":     {"mv": 2,  "mev": 4,  "mav": 8,  "mrv": 12},
    "abs":          {"mv": 0,  "mev": 4,  "mav": 16, "mrv": 25},
    "core":         {"mv": 0,  "mev": 4,  "mav": 16, "mrv": 25},
    "erectors":     {"mv": 2,  "mev": 4,  "mav": 10, "mrv": 16},
    "traps":        {"mv": 2,  "mev": 4,  "mav": 15, "mrv": 22},
    # No published RP landmark — practitioner extrapolation:
    "external_rotators": {"mv": 0,  "mev": 2,  "mav": 6,  "mrv": 12},
    "adductors":    {"mv": 0,  "mev": 2,  "mav": 8,  "mrv": 12},
    "neck":         {"mv": 0,  "mev": 2,  "mav": 6,  "mrv": 12},
}

# Canonicalise the muscle tokens that appear in exercises-database.md to the
# snake_case keys used everywhere else (and in VOLUME_LANDMARKS).
MUSCLE_ALIASES = {
    "chest": "chest", "upper chest": "upper_chest",
    "back": "back", "lats": "lats",
    "biceps": "biceps", "triceps": "triceps",
    "quads": "quads", "hamstrings": "hamstrings",
    "glutes": "glutes", "adductors": "adductors",
    "calves": "calves", "forearms": "forearms",
    "abs": "abs", "core": "core",
    "erectors": "erectors", "traps": "traps",
    "neck": "neck",
    "front delt": "front_delts", "front delts": "front_delts",
    "side delt": "side_delts",  "side delts":  "side_delts",
    "rear delt": "rear_delts",  "rear delts":  "rear_delts",
    "external rotators": "external_rotators",
    "shoulders": "shoulders",   "full body": "full_body",
    "posterior chain": None,    # too broad to assign — skip as primary
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
    "tier_b_stalled_lifts_count":      2,      # Tuchscherer reactive-deload

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

    # ---- Tier D: green (default — train as planned) ----
    "tier_d_recovery_score_min":       5.5,
    "tier_d_tsb_lo":                  -10.0,
    "tier_d_tsb_hi":                   0.0,

    # ---- Tier E: over-recovered / taper warning ----
    "tier_e_tsb_high":                 10.0,
    "tier_e_tsb_sustained_days":       5,
}


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
