"""Five-tier session recommendation gate and tier history."""
from __future__ import annotations

from datetime import date, timedelta

from health_recovery import _z_score_signal, recovery_score
from health_windowing import baseline_60d, latest_metric, _mean_or_none, _values_in_window
from parsing import _parse_iso_date


def _muscles_over_mrv(weekly_volume: dict | None) -> list[str]:
    """Return the list of muscle names whose per-week volume exceeds MRV."""
    if not weekly_volume:
        return []
    current = weekly_volume.get("current") or {}
    landmarks = weekly_volume.get("landmarks") or {}
    window_days = weekly_volume.get("window_days") or 28
    weeks_in_window = max(window_days / 7.0, 1.0)
    out = []
    for m, sets_in_window in current.items():
        per_wk = sets_in_window / weeks_in_window
        mrv = (landmarks.get(m) or {}).get("mrv")
        if mrv and per_wk > mrv:
            out.append(m)
    return sorted(out)


def _rhr_sustained_elevation_days(health_all: list[dict], today_d: date,
                                   bpm_above_baseline: float,
                                   baseline_days: int = 14) -> int:
    """Number of consecutive most-recent days where RHR >= baseline + threshold.

    Used by Tier A's "RHR sustained +10 bpm for 3 days" trigger.
    """
    baseline = _mean_or_none(
        _values_in_window(health_all, "resting_hr", today_d, baseline_days)
    )
    if baseline is None:
        return 0
    threshold = baseline + bpm_above_baseline
    by_date: dict[date, float] = {}
    for e in health_all:
        v = e.get("resting_hr")
        if v is None:
            continue
        d = _parse_iso_date(e.get("date"))
        if d is None or d > today_d:
            continue
        try:
            by_date[d] = float(v)
        except (TypeError, ValueError):
            continue
    streak = 0
    cur = today_d
    while True:
        v = by_date.get(cur)
        if v is None or v < threshold:
            break
        streak += 1
        cur = cur - timedelta(days=1)
    return streak


def _wrist_temp_deviation_c(health_all: list[dict], today_d: date) -> float | None:
    """Latest wrist temp minus the 60-day mean. Positive = above baseline."""
    latest = latest_metric(health_all, "wrist_temp_c")
    baseline = baseline_60d(health_all, "wrist_temp_c", today_d)
    if not latest or baseline is None:
        return None
    return round(latest["value"] - baseline, 2)


def _z_for(health_all: list[dict], key: str, today_d: date,
           recent_days: int = 7, baseline_days: int = 60,
           invert: bool = False) -> float | None:
    """Personal z-score for a single signal. Thin wrapper around
    `_z_score_signal` that returns just the z value."""
    info = _z_score_signal(health_all, key, today_d, recent_days, baseline_days, invert=invert)
    return info["z"] if info else None


def _count_stalled_lifts(estimated_1rm: dict | None) -> int:
    """Count lifts with stalled_sessions >= 2 (the Tuchscherer reactive-deload
    trigger). Uses already-computed `estimated_1rm[ex].stalled_sessions`."""
    if not estimated_1rm:
        return 0
    n = 0
    for v in estimated_1rm.values():
        if not isinstance(v, dict):
            continue
        stalled = v.get("stalled_sessions")
        try:
            if stalled is not None and int(stalled) >= 2:
                n += 1
        except (TypeError, ValueError):
            continue
    return n


def _tsb_sustained_days(today_tsb: float | None, training_load: dict | None,
                        threshold: float, direction: str = "above") -> int:
    """Approximation: returns 1 when the current TSB hits the threshold
    in the given direction, otherwise 0. We don't have day-by-day TSB
    history in `training_load` (only today), so over-recovered "sustained"
    is approximated by current TSB + 7-day trend slope. The render layer
    computes the proper 14-day strip from `compute_tier_history`."""
    if today_tsb is None:
        return 0
    if direction == "above" and today_tsb >= threshold:
        return 1
    if direction == "below" and today_tsb <= threshold:
        return 1
    return 0


def compute_session_recommendation(*,
                                    recovery: dict | None,
                                    training_load: dict | None,
                                    acwr: dict | None,
                                    weekly_volume: dict | None,
                                    sleep_regularity: dict | None,
                                    sleep_summary: dict | None,
                                    estimated_1rm: dict | None,
                                    hr_at_volume_divergence: dict | None,
                                    deloads: list[str] | None,
                                    auto_deload_candidates: list[str] | None,
                                    health_all: list[dict],
                                    today_d: date,
                                    estimated_max_hr: float | None) -> dict:
    """Top-down 5-tier gate. First gate to fire wins. Returns the
    operational recommendation that the SKILL.md prompt MUST honor before
    generating any workout.

    Tiers (highest priority first):
      A — illness / acute rest
      B — reactive deload (HRV crash, TSB high fatigue, MRV breach,
          spike, stalled lifts, unmarked deload candidate)
      C — downgrade (modified strength is OK)
      D — green (train as planned)
      E — over-recovered (train normal + taper warning)

    Returns a dict with `tier`, `label`, `headline`, `substitute`,
    `rationale` list, and `override_*` fields.
    """
    from constants import SESSION_GATE_THRESHOLDS as T  # local import

    drivers = (recovery or {}).get("drivers") or []
    hrv_d = next((d for d in drivers if d.get("metric") == "hrv_sdnn"), None)
    rhr_d = next((d for d in drivers if d.get("metric") == "resting_hr"), None)
    hrv_z = hrv_d.get("z") if hrv_d else None
    rhr_z = rhr_d.get("z") if rhr_d else None
    recovery_score = (recovery or {}).get("score")

    tsb = (training_load or {}).get("tsb")
    wow_pct = (acwr or {}).get("wow_change_pct")

    over_mrv_muscles = _muscles_over_mrv(weekly_volume)
    n_over_mrv = len(over_mrv_muscles)

    wrist_temp_dev = _wrist_temp_deviation_c(health_all, today_d)
    rhr_streak = _rhr_sustained_elevation_days(
        health_all, today_d, T["tier_a_rhr_dev_bpm"], baseline_days=14)
    stalled = _count_stalled_lifts(estimated_1rm)

    sleep_means = (sleep_summary or {}).get("means_h") or {}
    sleep_7d_mean = sleep_means.get("total")
    sleep_last_night = None
    # Latest sleep_total_h value (within the last 2 days)
    for e in reversed(health_all):
        d = _parse_iso_date(e.get("date"))
        v = e.get("sleep_total_h")
        if d is None or v is None:
            continue
        if (today_d - d).days <= 1:
            try:
                sleep_last_night = float(v)
            except (TypeError, ValueError):
                pass
            break
        if (today_d - d).days > 2:
            break
    sri = (sleep_regularity or {}).get("sri")

    unmarked_deload_recent = False
    if auto_deload_candidates:
        for ds in auto_deload_candidates:
            d = _parse_iso_date(ds)
            if d is None:
                continue
            if (today_d - d).days <= 7:
                unmarked_deload_recent = True
                break

    hr_creep_muscles = []
    for muscle, info in (hr_at_volume_divergence or {}).items():
        hint = (info or {}).get("hint") or ""
        if hint.startswith("rising"):
            hr_creep_muscles.append(muscle)

    rationale: list[dict] = []

    def add(signal, value, threshold, note):
        rationale.append({
            "signal": signal, "value": value,
            "threshold": threshold, "note": note,
        })

    # ---- TIER A: illness / acute rest ----
    tier_a_fired = False
    if (wrist_temp_dev is not None and wrist_temp_dev >= T["tier_a_wrist_temp_dev_c"]
            and hrv_z is not None and hrv_z <= T["tier_a_hrv_z_paired_with_temp"]):
        tier_a_fired = True
        add("wrist_temp_c", wrist_temp_dev, T["tier_a_wrist_temp_dev_c"],
            f"+{wrist_temp_dev:.2f}°C vs 60-day baseline (pre-illness range per Oura)")
        add("hrv_sdnn_z", round(hrv_z, 2), T["tier_a_hrv_z_paired_with_temp"],
            "autonomic suppression alongside temperature rise")
    if rhr_streak >= T["tier_a_rhr_sustained_days"]:
        tier_a_fired = True
        add("rhr_sustained_days", rhr_streak, T["tier_a_rhr_sustained_days"],
            f"RHR sustained ≥+{T['tier_a_rhr_dev_bpm']:.0f} bpm above 14-day baseline for {rhr_streak} consecutive days")
    if (recovery_score is not None and recovery_score < T["tier_a_recovery_score_crash"]
            and hrv_z is not None and hrv_z <= T["tier_a_hrv_z_crash"]
            and rhr_z is not None and rhr_z >= T["tier_a_rhr_z_crash"]):
        tier_a_fired = True
        add("recovery_crash", recovery_score, T["tier_a_recovery_score_crash"],
            f"Recovery {recovery_score:.1f}/10 with HRV z {hrv_z:+.2f} and RHR z {rhr_z:+.2f} — autonomic crash triad")

    if tier_a_fired:
        return {
            "tier": "A",
            "label": "rest",
            "headline": "Rest today.",
            "substitute": {
                "kind": "rest",
                "prescription": "20-min easy walk · hydration · sleep priority · no structured exercise",
                "duration_min": 20,
                "notes": "Re-evaluate tomorrow. Resume normal training only when wrist temp + RHR return to baseline and HRV is back in the 60-day band.",
            },
            "rationale": rationale[:5],
            "override_allowed": True,
            "override_message": "If you insist on training, hold to RPE ≤6 and Zone 2 only. The default recommendation is rest.",
        }

    # ---- TIER B: reactive deload ----
    tier_b_fired = False
    tier_b_kind = None  # zone_2 / reactive_deload_week / mobility_sauna
    if tsb is not None and tsb <= T["tier_b_tsb_high_fatigue"]:
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "zone_2"
        add("tsb", tsb, T["tier_b_tsb_high_fatigue"],
            f"Freshness (TSB) {tsb:+.1f} ≤ {T['tier_b_tsb_high_fatigue']:.0f} — high accumulated fatigue")
    if hrv_z is not None and hrv_z <= T["tier_b_hrv_z_sustained"]:
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "zone_2"
        add("hrv_sdnn_z", round(hrv_z, 2), T["tier_b_hrv_z_sustained"],
            f"HRV z {hrv_z:+.2f} sustained below 60-day baseline (Altini maladaptation signal)")
    if n_over_mrv >= T["tier_b_muscles_over_mrv_count"]:
        tier_b_fired = True
        tier_b_kind = "reactive_deload_week"  # MRV breach forces the week-long deload
        names = ", ".join(over_mrv_muscles[:5])
        add("muscles_over_mrv", n_over_mrv, T["tier_b_muscles_over_mrv_count"],
            f"{n_over_mrv} muscles over MRV ({names}) — RP MRV-breach protocol triggers a reactive deload")
    if unmarked_deload_recent:
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "reactive_deload_week"
        add("auto_deload_candidate", "yes", "—",
            "auto-deload candidate flagged in the last 7 days; the data already looked like a deload was needed")
    if wow_pct is not None and wow_pct >= T["tier_b_wow_spike_pct"]:
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "zone_2"
        add("wow_change_pct", round(wow_pct, 1), T["tier_b_wow_spike_pct"],
            f"week-over-week training stress +{wow_pct:.0f}% — sharp ramp into red, cap the next 7 days at +10%")
    if stalled >= T["tier_b_stalled_lifts_count"]:
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "reactive_deload_week"
        add("stalled_lifts", stalled, T["tier_b_stalled_lifts_count"],
            f"{stalled} top lifts have stalled (≥2 consecutive sessions of regression) — Tuchscherer reactive-deload trigger")

    if tier_b_fired:
        if tier_b_kind == "reactive_deload_week":
            substitute = {
                "kind": "reactive_deload_week",
                "prescription": "deload week: cut working-set count to ~50%, hold loads, drop conditioning finishers, rotate over-MRV exercises to a different movement pattern",
                "duration_min": None,
                "notes": "Return to normal volume next week if recovery score ≥6 and HRV trend back in band.",
            }
            headline = "Reactive deload this week."
        else:
            zone2_hr = int((estimated_max_hr or 195) * 0.65) if estimated_max_hr else None
            zone2_hint = f" at ~{zone2_hr} bpm" if zone2_hr else ""
            substitute = {
                "kind": "zone_2",
                "prescription": f"Zone 2 cardio 45–60 min{zone2_hint} · mobility 15 min · sauna 15 min optional · no strength today",
                "duration_min": 60,
                "notes": "Re-evaluate tomorrow. If HRV recovers and TSB lifts, you can resume strength.",
            }
            headline = "Zone 2 day, not strength."
        return {
            "tier": "B",
            "label": "reactive_deload",
            "headline": headline,
            "substitute": substitute,
            "rationale": rationale[:5],
            "override_allowed": True,
            "override_message": "If you insist on strength, cap at RPE 6, drop volume by 50%, and skip the finisher.",
        }

    # ---- TIER C: downgrade (modified strength is fine) ----
    tier_c_fired = False
    if recovery_score is not None and T["tier_c_recovery_score_lo"] <= recovery_score <= T["tier_c_recovery_score_hi"]:
        tier_c_fired = True
        add("recovery_score", recovery_score, T["tier_c_recovery_score_hi"],
            f"Recovery {recovery_score:.1f}/10 — moderate (not critically low)")
    if hrv_z is not None and T["tier_c_hrv_z_lo"] < hrv_z <= T["tier_c_hrv_z_hi"]:
        tier_c_fired = True
        add("hrv_sdnn_z", round(hrv_z, 2), T["tier_c_hrv_z_hi"],
            f"HRV z {hrv_z:+.2f} mildly below baseline")
    if sleep_last_night is not None and sleep_last_night < T["tier_c_sleep_total_h_floor"]:
        tier_c_fired = True
        add("sleep_last_night_h", round(sleep_last_night, 2), T["tier_c_sleep_total_h_floor"],
            f"last night {sleep_last_night:.2f}h, below the {T['tier_c_sleep_total_h_floor']:.0f}h floor")
    elif sleep_7d_mean is not None and sleep_7d_mean < T["tier_c_sleep_7d_mean_floor"]:
        tier_c_fired = True
        add("sleep_7d_mean_h", round(sleep_7d_mean, 2), T["tier_c_sleep_7d_mean_floor"],
            f"7-day sleep mean {sleep_7d_mean:.2f}h below the {T['tier_c_sleep_7d_mean_floor']:.0f}h floor")
    if sri is not None and sri < T["tier_c_sri_floor"]:
        tier_c_fired = True
        add("sleep_regularity_index", round(sri, 1), T["tier_c_sri_floor"],
            f"SRI {sri:.0f} below UK Biobank bottom-quintile cutoff ({T['tier_c_sri_floor']:.0f})")
    if rhr_z is not None and rhr_z >= T["tier_c_rhr_z_floor"]:
        tier_c_fired = True
        add("rhr_z", round(rhr_z, 2), T["tier_c_rhr_z_floor"],
            f"RHR z {rhr_z:+.2f} above baseline")
    if n_over_mrv >= T["tier_c_muscles_over_mrv_count"]:
        tier_c_fired = True
        names = ", ".join(over_mrv_muscles[:5])
        add("muscles_over_mrv", n_over_mrv, T["tier_c_muscles_over_mrv_count"],
            f"{n_over_mrv} muscle(s) over MRV ({names}) — modify the affected groups")
    if hr_creep_muscles:
        tier_c_fired = True
        names = ", ".join(hr_creep_muscles[:5])
        add("hr_at_volume_divergence", len(hr_creep_muscles), 1,
            f"HR rising at constant volume on {names} — hold loads on those groups")

    if tier_c_fired:
        return {
            "tier": "C",
            "label": "downgrade",
            "headline": "Modified strength: hold loads, cut accessories.",
            "substitute": {
                "kind": "modified_strength",
                "prescription": f"keep the planned session pattern · −{T['tier_c_downgrade_volume_pct']:.0f}% volume on secondary lifts · hold loads on every working set · drop conditioning finisher · no PR attempts",
                "duration_min": None,
                "notes": "Compound lifts stay at planned volume; isolations halve. Re-assess tomorrow.",
            },
            "rationale": rationale[:5],
            "override_allowed": True,
            "override_message": "If recovery rebounds tomorrow, resume full volume.",
        }

    # ---- TIER E: over-recovered taper warning ----
    if tsb is not None and tsb >= T["tier_e_tsb_high"]:
        add("tsb", tsb, T["tier_e_tsb_high"],
            f"Freshness (TSB) {tsb:+.1f} ≥ {T['tier_e_tsb_high']:.0f} — fitness is bleeding off, you've been over-recovered")
        return {
            "tier": "E",
            "label": "over_recovered",
            "headline": "Train as planned — but you've been over-recovered, fitness is bleeding off.",
            "substitute": {
                "kind": "normal_strength",
                "prescription": "resume normal training load · don't sit in the taper any longer",
                "duration_min": None,
                "notes": "If TSB stays above +10 for another week without a race, you're losing CTL needlessly.",
            },
            "rationale": rationale[:3],
            "override_allowed": True,
            "override_message": "",
        }

    # ---- TIER D: green ----
    if recovery_score is not None:
        add("recovery_score", recovery_score, T["tier_d_recovery_score_min"],
            f"Recovery {recovery_score:.1f}/10 — green")
    if tsb is not None:
        add("tsb", tsb, None,
            f"Freshness (TSB) {tsb:+.1f} in the productive zone")
    return {
        "tier": "D",
        "label": "green",
        "headline": "Train as planned.",
        "substitute": {
            "kind": "normal_strength",
            "prescription": "execute the planned session with the load rules from SKILL.md §6",
            "duration_min": None,
            "notes": "Green light. Hard training is on the table today.",
        },
        "rationale": rationale[:3],
        "override_allowed": True,
        "override_message": "",
    }


# Tier-history strip: walk back N days, re-running the gate against a
# rolling-window view of `today`. Used for the Trajectory tab's
# "Decision history" component (last 14 days of tier classifications).

def compute_tier_history(*,
                         days: int = 14,
                         today_d: date,
                         health_all: list[dict],
                         monthly_sessions: list[dict],
                         weekly_volume: dict | None,
                         sleep_nights_all: list[dict],
                         sleep_regularity_today: dict | None,
                         sleep_summary_today: dict | None,
                         estimated_1rm: dict | None,
                         hr_at_volume_divergence: dict | None,
                         deloads: list[str] | None,
                         auto_deload_candidates: list[str] | None,
                         capabilities: dict,
                         estimated_max_hr: float | None,
                         estimated_rest_hr: float | None) -> list[dict]:
    """For each of the last ``days`` days, recompute the recovery score,
    training load (CTL/ATL/TSB), ACWR, and run the gate to determine that
    day's tier. Returns a list of ``{date, tier, dominant_signal}`` entries
    sorted oldest first.

    Approximation: weekly_volume, sleep_regularity, sleep_summary,
    estimated_1rm, hr_at_volume_divergence, deloads, and
    auto_deload_candidates use TODAY's snapshot at every back-step (these
    move slowly and a per-day recompute would be expensive). The history
    is most accurate for the fast-moving signals (recovery, TSB, ACWR) —
    which dominate Tier A/B classification anyway.
    """
    from cardio import compute_acwr, training_load_summary, trimp_per_session  # local
    out: list[dict] = []
    # Recompute per-session TRIMPs once over the full window; faster than
    # per-day. Then build training load and ACWR per back-step.
    trimps = trimp_per_session(monthly_sessions, estimated_max_hr, estimated_rest_hr)
    for offset in range(days - 1, -1, -1):
        d = today_d - timedelta(days=offset)
        # Lightweight per-day re-computations of the fast signals
        rec_d = recovery_score(health_all, d, capabilities)
        tl_d = training_load_summary(trimps, d)
        acwr_d = compute_acwr(trimps, d)
        rec_dict = compute_session_recommendation(
            recovery=rec_d,
            training_load=tl_d,
            acwr=acwr_d,
            weekly_volume=weekly_volume,
            sleep_regularity=sleep_regularity_today,
            sleep_summary=sleep_summary_today,
            estimated_1rm=estimated_1rm,
            hr_at_volume_divergence=hr_at_volume_divergence,
            deloads=deloads,
            auto_deload_candidates=auto_deload_candidates,
            health_all=health_all,
            today_d=d,
            estimated_max_hr=estimated_max_hr,
        )
        dominant_signal = ""
        rationale = rec_dict.get("rationale") or []
        if rationale:
            dominant_signal = rationale[0].get("signal") or ""
        out.append({
            "date": d.isoformat(),
            "tier": rec_dict["tier"],
            "label": rec_dict["label"],
            "dominant_signal": dominant_signal,
        })
    return out

