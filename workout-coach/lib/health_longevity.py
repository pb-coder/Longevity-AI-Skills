"""Longevity trajectory scoring and personal longevity-state parsing."""
from __future__ import annotations

from datetime import date, datetime


def vo2_percentile_age_sex(value: float | None, sex: str | None,
                            age: int | None) -> dict | None:
    """Resolve a VO2 max reading to its age-cohort percentile band.

    Returns a dict with the four reference points (p50/p75/p95/longevity)
    plus the user's current bucket and a human-readable label
    ("median for your age", "above average", "elite", "longevity-target").
    Returns ``None`` when sex/age unknown or no value provided.
    """
    from .constants import VO2MAX_NORMS, age_band  # local import
    if value is None:
        return None
    bands = age_band(VO2MAX_NORMS, sex or "", age if age is not None else 0)
    if not bands:
        return None
    p50, p75, p95, longevity = bands["p50"], bands["p75"], bands["p95"], bands["longevity"]
    if value < p50:
        label, status = "below median", "warn"
    elif value < p75:
        label, status = "above median", "amber"
    elif value < p95:
        label, status = "above-average", "good"
    elif value < longevity:
        label, status = "elite", "good"
    else:
        label, status = "longevity-target reached", "good"
    return {
        "value":       round(value, 1),
        "p50":         p50,
        "p75":         p75,
        "p95":         p95,
        "longevity":   longevity,
        "label":       label,
        "status":      status,
    }


def _safe_norm(value: float | None, lo: float, hi: float) -> float:
    """Linear normalize ``value`` from [lo, hi] to [0, 1], clamped."""
    if value is None or hi <= lo:
        return 0.0
    x = (value - lo) / (hi - lo)
    return max(0.0, min(1.0, x))


def compute_longevity_score(*, vo2_percentile: dict | None,
                            recovery: dict | None,
                            sleep_summary: dict | None,
                            sleep_regularity: dict | None,
                            acwr: dict | None,
                            cardio_zones: dict | None,
                            movement_consistency: dict | None,
                            bodyweight_trend_kg_per_week: float | None,
                            estimated_1rm: dict | None,
                            capabilities: dict | None = None) -> dict | None:
    """Composite Longevity Score (0-100) — the Trajectory tab headline.

    Weighted average of normalized inputs from ``LONGEVITY_SCORE_WEIGHTS``.
    Weights are renormalized to the subset of inputs that are present so
    a person with missing data isn't structurally penalized (same shape
    as ``recovery_score``).

    Returns ``{"score": float, "components": [...], "n_components": int,
    "bloodwork_pending": True}`` with per-component attribution
    (contribution to the final score) so the dashboard can render
    "what's pulling you up / down".

    The ``bloodwork_pending`` flag is always True until biomarker
    ingestion lands — the score is honest about what it doesn't see.
    """
    from .constants import LONGEVITY_SCORE_WEIGHTS
    components: dict[str, float] = {}

    # 1. VO2 percentile (longevity-most-predictive single signal)
    if vo2_percentile:
        v = vo2_percentile.get("value")
        p50, p95 = vo2_percentile.get("p50"), vo2_percentile.get("p95")
        long_t = vo2_percentile.get("longevity")
        if v is not None and p50 is not None and long_t is not None:
            # 50 baseline at p50, 100 at longevity target, 0 well below.
            if v >= long_t:
                components["vo2_percentile"] = 100.0
            elif v >= p95:
                components["vo2_percentile"] = 85.0 + 15.0 * (v - p95) / max(long_t - p95, 0.1)
            elif v >= p50:
                components["vo2_percentile"] = 50.0 + 35.0 * (v - p50) / max(p95 - p50, 0.1)
            else:
                components["vo2_percentile"] = max(0.0, 50.0 * (v / p50))

    # 2. HRV trend (recovery_score driver). Use the HRV component score
    # directly (0-10 mapped to 0-100).
    drivers = (recovery or {}).get("drivers") or []
    hrv_d = next((d for d in drivers if d.get("metric") == "hrv_sdnn"), None)
    if hrv_d and hrv_d.get("component_score") is not None:
        components["hrv_trend"] = hrv_d["component_score"] * 10.0
    rhr_d = next((d for d in drivers if d.get("metric") == "resting_hr"), None)
    if rhr_d and rhr_d.get("component_score") is not None:
        components["rhr_trend"] = rhr_d["component_score"] * 10.0

    # 3. Sleep regularity (UK Biobank mortality-relevant)
    if sleep_regularity and sleep_regularity.get("sri") is not None:
        sri = sleep_regularity["sri"]
        components["sleep_regularity"] = max(0.0, min(100.0, sri))

    # 4. Sleep quality (duration × deep+REM × efficiency)
    if sleep_summary:
        means = sleep_summary.get("means_h") or {}
        eff_block = sleep_summary.get("sleep_efficiency_pct") or {}
        total = means.get("total") or 0.0
        deep = means.get("deep") or 0.0
        rem = means.get("rem") or 0.0
        eff_mean = (eff_block.get("mean") if isinstance(eff_block, dict) else None)
        # Each sub-input normalized to [0, 1], averaged into a 0-100 score.
        dur_n = _safe_norm(total, 5.0, 8.0)
        dr_n = _safe_norm(deep + rem, 1.0, 3.0)
        eff_n = _safe_norm(eff_mean, 75.0, 95.0) if eff_mean is not None else None
        parts = [v for v in (dur_n, dr_n, eff_n) if v is not None]
        if parts:
            components["sleep_quality"] = 100.0 * sum(parts) / len(parts)

    # 5. ACWR sweet-spot adherence (closer to 1.0 in [0.8, 1.3] = higher)
    if acwr and acwr.get("ratio") is not None:
        r = acwr["ratio"]
        if 0.8 <= r <= 1.3:
            components["training_load_in_band"] = 100.0
        elif 0.5 <= r < 0.8:
            components["training_load_in_band"] = 50.0 + 50.0 * (r - 0.5) / 0.3
        elif 1.3 < r <= 1.5:
            components["training_load_in_band"] = 100.0 - 30.0 * (r - 1.3) / 0.2
        else:
            components["training_load_in_band"] = max(0.0, 50.0 - 25.0 * abs(r - 1.0))

    # 6. Z2 weekly minutes adherence (target 150)
    if cardio_zones:
        z2 = cardio_zones.get("z2") or 0
        z2_per_wk = z2 / 4.0  # cardio_zones is 28d window
        components["z2_weekly_adherence"] = _safe_norm(z2_per_wk, 0, 200.0) * 100.0

    # 7. Body composition trend (directional: depends on bw goal — without a
    # goal field we treat ANY directional change as informative; small
    # gains in a lean-bulk context = good. 0 weight change = 60 baseline.
    if bodyweight_trend_kg_per_week is not None:
        bt = bodyweight_trend_kg_per_week
        # +0.0 to +0.4 kg/wk = lean-bulk healthy range; >0.6 fat-mass risk;
        # negative = cutting or unintentional loss. Without goal context,
        # tight neutral band gets the highest score.
        if -0.1 <= bt <= 0.4:
            components["body_comp_trend"] = 75.0
        elif 0.4 < bt <= 0.6:
            components["body_comp_trend"] = 60.0
        else:
            components["body_comp_trend"] = 50.0

    # 8. Behavioral consistency (movement-min days ≥ threshold per week)
    if movement_consistency:
        days_28 = movement_consistency.get("days_28d") or 0
        # Target: 5 days/wk × 4 = 20 days in 28; floor 0 = 0 score.
        components["behavioral_consistency"] = _safe_norm(days_28, 0, 20.0) * 100.0

    # 9. Strength progression: average slope direction across tracked lifts.
    if estimated_1rm:
        slopes = [v.get("slope_kg_per_4w") for v in estimated_1rm.values()
                  if isinstance(v, dict) and v.get("slope_kg_per_4w") is not None]
        if slopes:
            pos = sum(1 for s in slopes if s > 0.0)
            neutral = sum(1 for s in slopes if -0.5 <= s <= 0.5)
            pos_share = (pos + 0.5 * neutral) / len(slopes)
            components["strength_progression"] = pos_share * 100.0

    if not components:
        return None

    weights = {k: LONGEVITY_SCORE_WEIGHTS[k] for k in components.keys()
               if k in LONGEVITY_SCORE_WEIGHTS}
    total_w = sum(weights.values())
    if total_w <= 0:
        return None
    score = sum(weights[k] * components[k] for k in weights) / total_w

    # Per-component attribution for the dashboard's drilldown.
    attribution: list[dict] = []
    for k, v in components.items():
        norm_w = weights[k] / total_w
        attribution.append({
            "name":         k,
            "score":        round(v, 1),
            "weight":       round(norm_w, 3),
            "contribution": round(v * norm_w, 2),
        })
    attribution.sort(key=lambda a: a["contribution"], reverse=True)

    if score >= 80.0:
        band = "good"
        label = "excellent trajectory"
    elif score >= 65.0:
        band = "good"
        label = "on a good trajectory"
    elif score >= 50.0:
        band = "amber"
        label = "average trajectory"
    else:
        band = "warn"
        label = "needs attention"

    # Status classification — honest about gaps.
    #
    # Cornerstone = VO2 percentile (the single strongest longevity
    # predictor; the score loses most of its meaning without it).
    # Tracked = every other input. When some tracked inputs are missing
    # the score still computes but we surface what's absent so the user
    # can populate them.
    CORNERSTONE = "vo2_percentile"
    TRACKED_INPUTS = list(LONGEVITY_SCORE_WEIGHTS.keys())
    present_names = set(components.keys())
    missing_names = [n for n in TRACKED_INPUTS if n not in present_names]

    # Friendly hints for each missing input — only shown when the user
    # can actually act on them. Structural source limitations (e.g. SRI
    # requires segment-level sleep timestamps that HealthAutoExport
    # doesn't produce) are filtered out below via INPUT_CAPABILITY_REQ so
    # the dashboard doesn't punish people for a tooling boundary they
    # can't move.
    HINTS = {
        "vo2_percentile":         "Needs both age (from profile.csv birthday) AND sex (profile.csv sex field). Apple Health typically logs VO2max within a week of any outdoor run.",
        "hrv_trend":              "Needs ~7 consecutive nights of HRV (SDNN) data from the Apple Watch.",
        "rhr_trend":              "Needs ~7 consecutive days of resting heart rate readings from the Apple Watch.",
        "sleep_regularity":       "Needs ~14 consecutive nights of sleep data with per-segment bedtime / waketime timestamps.",
        "sleep_quality":          "Needs at least one logged sleep night with total / deep / REM in the 28-day window.",
        "training_load_in_band":  "Needs at least one cardio session with average HR in the last 28 days to compute the ACWR.",
        "z2_weekly_adherence":    "Needs at least one cardio session with average HR in the last 28 days.",
        "body_comp_trend":        "Needs at least 8 fasted bodyweight readings to compute a per-week trend.",
        "behavioral_consistency": "Needs daily Apple exercise minutes from the last 28 days.",
        "strength_progression":   "Needs at least 4 weeks of strength logs with progressive weights or reps.",
    }
    # Each input maps to the SOURCE_CAPABILITIES flag it depends on (or
    # None if it's source-independent / user-populatable). When the
    # current source returns False for the required flag, the input is
    # filtered from the user-facing missing list — it's structurally
    # unavailable, not "not yet populated".
    INPUT_CAPABILITY_REQ = {
        "sleep_regularity": "sleep_regularity",
    }
    caps = capabilities or {}
    missing_inputs = []
    for n in missing_names:
        req = INPUT_CAPABILITY_REQ.get(n)
        if req is not None and caps.get(req) is False:
            continue
        missing_inputs.append({"name": n, "hint": HINTS.get(n, "")})

    # Bloodwork lives in its own top-level flag (panel ingestion isn't
    # wired yet) but the user reads it as "another outstanding longevity
    # item." Surface it as a synthetic missing-input entry so the
    # longevity-score card lists everything outstanding in one place —
    # users no longer need to cross-reference the body-comp / metabolic
    # domain cards to find the full picture.
    missing_inputs.append({
        "name": "bloodwork",
        "hint": ("Foundational panel: lipids (ApoB, Lp(a)), fasting "
                 "glucose / HbA1c / insulin, hsCRP, eGFR. Covers the "
                 "metabolic + body-comp gaps."),
    })

    if CORNERSTONE not in present_names:
        status = "incomplete"
        status_label = "Incomplete"
        # When the cornerstone is missing the score still computes but it
        # leans on the wrong signals (e.g. Apple-ring movement count
        # carrying outsized weight). Suppress the confident band/label.
        band = "muted"
        label = "Incomplete — VO2 max percentile cannot be resolved"
    elif missing_names:
        status = "partial"
        status_label = f"Partial — {len(present_names)} of {len(TRACKED_INPUTS)} inputs"
    else:
        status = "complete"
        status_label = "Complete"

    return {
        "score":             round(score, 1),
        "band":              band,
        "label":             label,
        "status":            status,
        "status_label":      status_label,
        "n_components":      len(components),
        "n_tracked_total":   len(TRACKED_INPUTS),
        "components":        attribution,
        "missing_inputs":    missing_inputs,
        "bloodwork_pending": True,
        "note":              "Score excludes biomarkers (lipids, glucose, ApoB, hsCRP) until a panel is on file.",
    }


# =============================================================================
# 5-tier session recommendation gate
# =============================================================================
#
# The Today tab calls this BEFORE generating any workout. It decides which of
# Tier A (rest) / B (reactive deload) / C (downgrade) / D (green) / E
# (over-recovered) the user is in, based on the existing signals already in
# the JSON. The SKILL.md Phase 2 prompt is required to honor the result —
# this is the deterministic single source of truth so the LLM can't
# rationalize past it.

def read_longevity_state(person: str, today_d: date) -> dict | None:
    """Parse the person's longevity ``.md`` files into a structured state
    block for the Trajectory tab's personalized risk panel.

    Reads (where present) ``profile.md``, ``state.md``, ``interventions.md``,
    ``biomarkers.md`` from ``<root>/<Person>/data/longevity/`` and surfaces:

    - ``has_profile``: whether a longevity profile exists for this person
    - ``age`` computed from DOB
    - ``sex``, ``height_cm``, ``location``
    - ``family_history``: list of strings
    - ``constraints``: long-term constraints (vegan, alcohol-free, etc.)
    - ``active_conditions``: list of strings
    - ``medications``: list of strings
    - ``bloodwork_status``: "none-yet" / "panel-on-file"
    - ``risk_flags``: list of dicts {key, label, status, hint} where
      ``status`` is one of "tracked" / "due" / "overdue" / "active".

    Returns ``None`` when the directory doesn't exist (so <OtherPerson> without a
    longevity/ folder gets a clean "no profile" state). Renderer reads
    this directly.
    """
    from pathlib import Path as _Path
    skills_root = _Path(__file__).resolve().parents[3]
    person_root = skills_root / person / "data" / "longevity"
    if not person_root.exists():
        return None

    def _read(name: str) -> str:
        path = person_root / name
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    profile_md = _read("profile.md")
    state_md = _read("state.md")
    interventions_md = _read("interventions.md")
    biomarkers_md = _read("biomarkers.md")

    out: dict = {"has_profile": True}

    # Parse DOB / sex / height / location
    import re as _re
    dob_match = _re.search(r"Date of birth.*?(\d{4}-\d{2}-\d{2})", profile_md)
    if dob_match:
        try:
            dob = datetime.strptime(dob_match.group(1), "%Y-%m-%d").date()
            out["dob"] = dob.isoformat()
            out["age"] = (today_d - dob).days // 365
        except ValueError:
            pass
    sex_match = _re.search(r"Sex.*?:\s*([A-Za-z]+)", profile_md)
    if sex_match:
        out["sex"] = sex_match.group(1).strip().lower()
    height_match = _re.search(r"Height.*?:\s*([\d.]+)\s*cm", profile_md)
    if height_match:
        out["height_cm"] = float(height_match.group(1))
    loc_match = _re.search(r"Location.*?:\s*([^\n]+)", profile_md)
    if loc_match:
        out["location"] = loc_match.group(1).strip()

    # Family history block
    fam_lines: list[str] = []
    in_fam = False
    for ln in profile_md.splitlines():
        if ln.strip().lower().startswith("# family history"):
            in_fam = True
            continue
        if in_fam:
            if ln.startswith("#"):
                break
            if ln.strip().startswith("- "):
                fam_lines.append(ln.strip()[2:].strip())
    out["family_history"] = fam_lines

    # Long-term constraints
    cons_lines: list[str] = []
    in_cons = False
    for ln in profile_md.splitlines():
        if ln.strip().lower().startswith("# long-term constraints"):
            in_cons = True
            continue
        if in_cons:
            if ln.startswith("#"):
                break
            if ln.strip().startswith("- "):
                cons_lines.append(ln.strip()[2:].strip())
    out["constraints"] = cons_lines

    # Active conditions
    cond_lines: list[str] = []
    in_cond = False
    for ln in state_md.splitlines():
        if ln.strip().lower().startswith("# active conditions"):
            in_cond = True
            continue
        if in_cond:
            if ln.startswith("# ") and "active conditions" not in ln.lower():
                break
            if ln.strip().startswith("- "):
                cond_lines.append(ln.strip()[2:].strip())
    out["active_conditions"] = cond_lines

    # Medications
    med_lines: list[str] = []
    in_med = False
    for ln in state_md.splitlines():
        if ln.strip().lower().startswith("# current medications"):
            in_med = True
            continue
        if in_med:
            if ln.startswith("# ") and "medication" not in ln.lower():
                break
            if ln.strip().startswith("- "):
                med_lines.append(ln.strip()[2:].strip())
    out["medications"] = med_lines

    # Bloodwork status: heuristic — "No blood work conducted yet" / dated panel
    if "no blood work" in biomarkers_md.lower() or "first panel planned" in biomarkers_md.lower():
        out["bloodwork_status"] = "none-yet"
    elif _re.search(r"##\s+\d{4}-\d{2}-\d{2}", biomarkers_md):
        out["bloodwork_status"] = "panel-on-file"
    else:
        out["bloodwork_status"] = "unknown"

    # Build personalized risk flags from parsed text.
    flags: list[dict] = []
    profile_text = (profile_md + state_md).lower()
    family_text = " ".join(fam_lines).lower()
    cond_text = " ".join(cond_lines).lower()
    med_text = " ".join(med_lines).lower()
    constraints_text = " ".join(cons_lines).lower()

    if "parkinson" in family_text:
        flags.append({
            "key":    "parkinson_surveillance",
            "label":  "Parkinson early-marker watch",
            "status": "tracked",
            "hint":   "Family-history marker present. Watch REM sleep behavior, olfactory function, and autonomic symptoms.",
        })
    if "prep" in med_text or "prep" in (state_md.lower()):
        flags.append({
            "key":    "prep_monitoring",
            "label":  "PrEP renal + BMD monitoring",
            "status": "due" if out.get("bloodwork_status") == "none-yet" else "tracked",
            "hint":   "Tenofovir is associated with renal and bone-density changes. eGFR (cystatin-C variant) + DEXA recommended at baseline and periodically.",
        })
    if "vegan" in constraints_text or "vegan" in profile_text:
        flags.append({
            "key":    "vegan_micronutrient_panel",
            "label":  "Vegan micronutrient panel",
            "status": "due" if out.get("bloodwork_status") == "none-yet" else "tracked",
            "hint":   "Test ferritin (not just hemoglobin), homocysteine (functional B12), serum + spot urine zinc / iodine, omega-3 index, 25-OH-D.",
        })
    # High-latitude vitamin D winter window. Keep the trigger generic:
    # private locations live in per-person data, not committed code.
    location_text = (out.get("location") or "").lower()
    high_latitude = (
        "high latitude" in location_text
        or "northern europe" in location_text
        or bool(_re.search(r"\b(?:4[8-9]|[5-8]\d)(?:\.\d+)?\s*(?:°?\s*n|north)\b", location_text))
    )
    if high_latitude:
        month = today_d.month
        in_winter = month <= 3 or month >= 10
        flags.append({
            "key":    "vitamin_d_winter",
            "label":  "Vitamin D supplementation window",
            "status": "active" if in_winter else "tracked",
            "hint":   ("Cutaneous synthesis is near zero during winter at high latitudes. "
                       "Test 25-OH-D late winter to isolate the supplementation effect.")
                       if in_winter else "Outside the supplementation-mandatory window.",
        })
    if "atopic dermatitis" in cond_text and "active" in cond_text:
        flags.append({
            "key":    "atopic_dermatitis",
            "label":  "Atopic dermatitis",
            "status": "active",
            "hint":   "Active on hands. Topical cortisone for flares, hand cream 2-3x/day. Watch for sleep impact from itch.",
        })
    if out.get("bloodwork_status") == "none-yet":
        flags.append({
            "key":    "first_blood_panel",
            "label":  "First lab panel",
            "status": "due",
            "hint":   "Foundational longevity panel: lipids (ApoB, Lp(a), LDL, HDL, TG), fasting glucose, HbA1c, fasting insulin, hsCRP, eGFR, ferritin, B12, 25-OH-D.",
        })
    out["risk_flags"] = flags

    return out
