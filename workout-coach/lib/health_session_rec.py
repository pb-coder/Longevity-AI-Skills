"""Five-tier session recommendation gate and tier history."""
from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tracker.contracts import SessionRecommendation, SessionRationaleEntry  # noqa: F401
from .health_recovery import _z_score_signal, recovery_score
from .health_windowing import baseline_60d, latest_metric, _mean_or_none, _values_in_window
from .parsing import _parse_iso_date


def _muscles_over_mrv(weekly_volume: dict | None) -> list[str]:
    """Return the list of muscle names whose per-week volume exceeds MRV."""
    if not weekly_volume:
        return []
    current = weekly_volume.get("current") or {}
    landmarks = weekly_volume.get("landmarks") or {}
    out = []
    for m, per_wk in current.items():
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
    latest = latest_metric(health_all, "wrist_temp_c", today_d)
    baseline = baseline_60d(health_all, "wrist_temp_c", today_d)
    if not latest or baseline is None:
        return None
    return round(latest["value"] - baseline, 2)


def _count_stalled_lifts(estimated_1rm: dict | None) -> int:
    """Count lifts with stalled_sessions >= 2. Raw flat-e1RM count, kept for
    backward compatibility. NOT used by the gate anymore — see
    `_genuinely_stalled_lifts`, which excludes comeback lifts and lifts still
    progressing so a returning trainee holding loads isn't read as fatigue."""
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


def _genuinely_stalled_lifts(estimated_1rm: dict | None) -> int:
    """Count lifts that are genuinely stalled *at their ceiling* — the only
    kind that justifies a reactive deload.

    `stalled_sessions` alone means "e1RM held flat within ±0.5kg for N
    sessions" (see strength.py). Flatness is NOT fatigue:
      - a lift well below its best is being re-built after a layoff; repeating
        a conservative load there is intended, not a stall, so exclude it
        (`current < 0.9 * best`).
      - a lift whose 4-week slope is still positive is progressing despite a
        flat last pair; exclude it (`slope_kg_per_4w > 0`).
    What remains — flat, at/near best, not trending up — is a true plateau.
    """
    if not estimated_1rm:
        return 0
    n = 0
    for v in estimated_1rm.values():
        if not isinstance(v, dict):
            continue
        try:
            stalled = v.get("stalled_sessions")
            if stalled is None or int(stalled) < 2:
                continue
        except (TypeError, ValueError):
            continue
        cur = v.get("current_e1rm_kg")
        best = v.get("best_e1rm_kg")
        if cur is None or best is None or best <= 0:
            continue
        if cur < 0.9 * best:          # comeback / re-building — not a stall
            continue
        slope = v.get("slope_kg_per_4w")
        if slope is not None and slope > 0:   # still progressing
            continue
        n += 1
    return n


def _reactive_deload_served(deloads: list[str] | None, today_d: date,
                            recovery_score: float | None, hrv_z: float | None,
                            strength_tsb: float | None,
                            within_days: int = 10) -> bool:
    """True when a marked deload happened recently AND the athlete has
    rebounded, so re-prescribing a reactive deload would just loop.

    Encodes the gate's own note ("return to normal volume next week if
    recovery score >=6 and HRV trend back in band"). When True, the *slow*
    Tier B triggers are suppressed so the gate can climb back to C/D. Acute
    triggers (illness, MRV breach, week-over-week spike) are never gated by
    this.
    """
    recent = False
    for ds in deloads or []:
        d = _parse_iso_date(ds)
        if d is not None and 0 <= (today_d - d).days <= within_days:
            recent = True
            break
    if not recent:
        return False
    if recovery_score is None or recovery_score < 6.0:
        return False
    if hrv_z is not None and hrv_z < -0.5:
        return False
    if strength_tsb is not None and strength_tsb < 0:
        return False
    return True


def _expected_tier_c_rebound_by_session(
    *,
    deloads: list[str] | None,
    today_d: date,
    recovery_score: float | None,
    hr_creep_muscles: list[str],
) -> int:
    """Return the last workout slot that should stay Tier C modified.

    Tier C is generated once, but the workout file usually spans several
    sessions. Keep the default short (slot 1), and extend to slot 2 when
    the visible signals are more likely to persist into the early week.
    The cap at slot 2 is intentional: longer changes should come from a
    fresh /coach run rather than stale recovery-gate state.
    """
    recent_deload = False
    for ds in deloads or []:
        d = _parse_iso_date(ds)
        if d is not None and 0 <= (today_d - d).days <= 7:
            recent_deload = True
            break
    if recent_deload or hr_creep_muscles:
        return 2
    if recovery_score is not None and recovery_score <= 5.0:
        return 2
    return 1


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
                                    estimated_max_hr: float | None,
                                    bodyweight_trend: float | None = None) -> SessionRecommendation:
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
    from .constants import SESSION_GATE_THRESHOLDS as T  # local import

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
    stalled = _genuinely_stalled_lifts(estimated_1rm)

    # ---- Context flags that gate the SLOW (proxy) downgrade/deload triggers.
    # Acute triggers (illness, MRV breach, week-over-week spike) ignore these.
    # The passed `training_load` is strength-scoped (read_tracker + tier
    # history both feed strength TSB), so `tsb` here is strength freshness.
    strength_tsb = tsb
    over_recovered = strength_tsb is not None and strength_tsb >= T["tier_e_tsb_high"]
    bulking = bodyweight_trend is not None and bodyweight_trend >= 0.10
    recovery_green = (recovery_score is not None
                      and recovery_score >= T["tier_d_recovery_score_min"])
    deload_served = _reactive_deload_served(
        deloads, today_d, recovery_score, hrv_z, strength_tsb)
    # Slow fatigue proxies don't fire when the athlete is over-recovered
    # (you can't be peaked and fatigued at once) or has just rebounded from a
    # served deload.
    suppress_slow = over_recovered or deload_served
    # A flat-at-ceiling stall is only a deload trigger when corroborated by an
    # independent fatigue signal — never on flat loads alone.
    stalled_corroborated = (
        (recovery_score is not None and recovery_score < T["tier_d_recovery_score_min"])
        or (strength_tsb is not None and strength_tsb < 0)
        or (hrv_z is not None and hrv_z <= T["tier_b_hrv_z_sustained"])
    )

    # Corroboration for the SOFT recovery/HRV Tier-C triggers and the Tier-D
    # floor guard. HRV is the dominant input to recovery_score, so a
    # "moderate" score and a "mildly-low HRV" reading are the SAME signal,
    # not two independent reasons. A single soft dip must not cut training
    # volume (or force a no-PR hold) while the athlete is fresh — you cannot
    # be peaked and fatigued at once. So the soft band only bites when
    # recovery is genuinely low (below the hard floor) OR freshness is
    # actually negative (carrying real load, strength TSB below the
    # carrying-load boundary). A genuinely low score still fires on its own.
    # This mirrors the corroboration the HR-creep and stalled-lift triggers
    # already require, applied to the two triggers that lacked it.
    recovery_genuinely_low = (
        recovery_score is not None and recovery_score < T["tier_c_recovery_hard_floor"]
    )
    under_real_load = (
        strength_tsb is not None and strength_tsb < T["tier_c_soft_tsb_floor"]
    )
    soft_dip_actionable = recovery_genuinely_low or under_real_load

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

    rationale: list[SessionRationaleEntry] = []

    def add(signal: str, value, threshold, note: str) -> None:
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
    # NOTE: rhr_z is the INVERTED recovery z (positive = RHR below baseline =
    # favorable). An autonomic crash means RHR is ELEVATED, i.e. z is strongly
    # negative — hence `<= -threshold`, not `>= threshold`.
    if (recovery_score is not None and recovery_score < T["tier_a_recovery_score_crash"]
            and hrv_z is not None and hrv_z <= T["tier_a_hrv_z_crash"]
            and rhr_z is not None and rhr_z <= -T["tier_a_rhr_z_crash"]):
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
    # Triggers split into ACUTE (always fire) and SLOW (gated by
    # `suppress_slow` so an over-recovered or just-rebounded athlete isn't
    # pinned in deload by a proxy signal).
    tier_b_fired = False
    tier_b_kind = None  # zone_2 / reactive_deload_week / mobility_sauna
    # SLOW: high accumulated fatigue. Suppressed only by a served-deload
    # rebound (over-recovery can't coexist with TSB ≤ -15).
    if (tsb is not None and tsb <= T["tier_b_tsb_high_fatigue"]
            and not deload_served):
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "zone_2"
        add("tsb", tsb, T["tier_b_tsb_high_fatigue"],
            f"Freshness (TSB) {tsb:+.1f} ≤ {T['tier_b_tsb_high_fatigue']:.0f} — high accumulated fatigue")
    # SLOW: sustained HRV suppression.
    if (hrv_z is not None and hrv_z <= T["tier_b_hrv_z_sustained"]
            and not suppress_slow):
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "zone_2"
        add("hrv_sdnn_z", round(hrv_z, 2), T["tier_b_hrv_z_sustained"],
            f"HRV z {hrv_z:+.2f} sustained below 60-day baseline (Altini maladaptation signal)")
    # ACUTE: MRV breach forces the week-long deload regardless of context.
    if n_over_mrv >= T["tier_b_muscles_over_mrv_count"]:
        tier_b_fired = True
        tier_b_kind = "reactive_deload_week"
        names = ", ".join(over_mrv_muscles[:5])
        add("muscles_over_mrv", n_over_mrv, T["tier_b_muscles_over_mrv_count"],
            f"{n_over_mrv} muscles over MRV ({names}) — RP MRV-breach protocol triggers a reactive deload")
    # SLOW: an auto-deload candidate is stale once a deload was already served.
    if unmarked_deload_recent and not deload_served:
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "reactive_deload_week"
        add("auto_deload_candidate", "yes", "—",
            "auto-deload candidate flagged in the last 7 days; the data already looked like a deload was needed")
    # ACUTE: a sharp week-over-week training-stress spike, regardless of context.
    if wow_pct is not None and wow_pct >= T["tier_b_wow_spike_pct"]:
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "zone_2"
        add("wow_change_pct", round(wow_pct, 1), T["tier_b_wow_spike_pct"],
            f"week-over-week training stress +{wow_pct:.0f}% — sharp ramp into red, cap the next 7 days at +10%")
    # SLOW: genuine ceiling-stall, but ONLY when corroborated by fatigue.
    # Flat loads on isolations / comeback lifts no longer force a deload.
    if (stalled >= T["tier_b_stalled_lifts_count"]
            and stalled_corroborated and not suppress_slow):
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "reactive_deload_week"
        add("stalled_lifts", stalled, T["tier_b_stalled_lifts_count"],
            f"{stalled} top lifts stalled at/near best for ≥2 sessions and not progressing, with a corroborating fatigue signal — Tuchscherer reactive-deload trigger")

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
    if (recovery_score is not None
            and T["tier_c_recovery_score_lo"] <= recovery_score <= T["tier_c_recovery_score_hi"]
            and soft_dip_actionable):
        tier_c_fired = True
        _why = ("genuinely low" if recovery_genuinely_low
                else "moderate, and freshness is negative (carrying load)")
        add("recovery_score", recovery_score, T["tier_c_recovery_score_hi"],
            f"Recovery {recovery_score:.1f}/10 — {_why}")
    if (hrv_z is not None and T["tier_c_hrv_z_lo"] < hrv_z <= T["tier_c_hrv_z_hi"]
            and not over_recovered and soft_dip_actionable):
        tier_c_fired = True
        add("hrv_sdnn_z", round(hrv_z, 2), T["tier_c_hrv_z_hi"],
            f"HRV z {hrv_z:+.2f} below baseline, corroborated by low recovery or negative freshness")
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
    # rhr_z is inverted (positive = RHR below baseline = good). RHR ELEVATED
    # above baseline is the unfavorable case, so test the negative tail.
    if rhr_z is not None and rhr_z <= -T["tier_c_rhr_z_floor"]:
        tier_c_fired = True
        add("rhr_z", round(rhr_z, 2), -T["tier_c_rhr_z_floor"],
            f"RHR z {rhr_z:+.2f} — resting HR elevated above baseline")
    if n_over_mrv >= T["tier_c_muscles_over_mrv_count"]:
        tier_c_fired = True
        names = ", ".join(over_mrv_muscles[:5])
        add("muscles_over_mrv", n_over_mrv, T["tier_c_muscles_over_mrv_count"],
            f"{n_over_mrv} muscle(s) over MRV ({names}) — modify the affected groups")
    # HR creep escalates to a session-wide downgrade ONLY when it's plausibly
    # fatigue AND corroborated by systemic under-recovery. Confounder guards:
    # a systemic shift across many muscles (bodyweight gain on a bulk, summer
    # heat) is NOT per-muscle fatigue. Corroboration guard: a localized HR
    # drift while overall recovery is fine and freshness is positive is weak
    # evidence for slashing session volume — the per-muscle "hold those groups,
    # don't add sets" rule (SKILL §19, applied at planning time) covers it
    # without gutting the workout. Require genuine moderate recovery (< the
    # Tier C ceiling) OR negative strength freshness before downgrading. This
    # mirrors the corroboration the stalled-lifts trigger already requires.
    systemic_hr_shift = "systemic_session_hr" in (hr_at_volume_divergence or {})
    hr_creep_corroborated = (
        (recovery_score is not None and recovery_score < T["tier_c_recovery_score_hi"])
        or (strength_tsb is not None and strength_tsb < 0)
    )
    hr_creep_actionable = (
        len(hr_creep_muscles) >= 2
        and not systemic_hr_shift
        and not bulking
        and not over_recovered
        and hr_creep_corroborated
    )
    if hr_creep_actionable:
        tier_c_fired = True
        names = ", ".join(hr_creep_muscles[:5])
        add("hr_at_volume_divergence", len(hr_creep_muscles), 2,
            f"HR rising at constant volume on {names} with no confounder, plus moderate recovery — hold loads on those groups")

    if tier_c_fired:
        rebound_by_session = _expected_tier_c_rebound_by_session(
            deloads=deloads,
            today_d=today_d,
            recovery_score=recovery_score,
            hr_creep_muscles=hr_creep_muscles,
        )
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
            "override_message": (
                f"Keep Tier C modifications through workout {rebound_by_session}; "
                "later slots can resume full volume only if recovery rebounds."
            ),
            "expected_rebound_by_session": rebound_by_session,
        }

    if (recovery_score is not None and recovery_score < T["tier_d_recovery_score_min"]
            and soft_dip_actionable):
        add("recovery_score", recovery_score, T["tier_d_recovery_score_min"],
            f"Recovery {recovery_score:.1f}/10 below green floor, with genuinely low recovery or negative freshness — hold load, no PR attempts")
        return {
            "tier": "C",
            "label": "hold_load",
            "headline": "Modified strength: hold loads, no PR attempts.",
            "substitute": {
                "kind": "modified_strength",
                "prescription": "keep the planned movement pattern · hold loads · no PR attempts · skip conditioning finisher",
                "duration_min": None,
                "notes": "This is the Tier-D floor guard: not a deload, but not green.",
            },
            "rationale": rationale[:5],
            "override_allowed": True,
            "override_message": "Resume normal load progression once recovery is back above the green floor.",
            "expected_rebound_by_session": 1,
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
    else:
        # Data gap: no recent health import means the recovery score is blind.
        # Don't let a confounded proxy ratchet the plan down — surface the gap
        # and lean on freshness (TSB) instead of guessing fatigue.
        add("recovery_unavailable", None, None,
            "Recovery score unavailable (no recent health import) — leaning on "
            "freshness (TSB). Import a fresh export to restore the recovery read.")
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
                         estimated_rest_hr: float | None,
                         bodyweight_trend: float | None = None) -> list[dict]:
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
    from .cardio import compute_acwr, training_load_summary, trimp_per_session  # local
    out: list[dict] = []
    # Recompute per-session TRIMPs once over the full window; faster than
    # per-day. Then build training load and ACWR per back-step.
    trimps = trimp_per_session(monthly_sessions, estimated_max_hr, estimated_rest_hr)
    strength_trimps = [t for t in trimps if t.get("kind") == "strength"]
    for offset in range(days - 1, -1, -1):
        d = today_d - timedelta(days=offset)
        # Lightweight per-day re-computations of the fast signals
        rec_d = recovery_score(health_all, d, capabilities)
        tl_all_d = training_load_summary(trimps, d)
        # Strength-scoped TSB (whole-body fallback when no strength TRIMP yet),
        # mirroring read_tracker's live gate so cardio blocks don't paint the
        # decision-history strip as strength fatigue.
        tl_strength_d = training_load_summary(strength_trimps, d)
        tl_d = tl_strength_d if tl_strength_d.get("tsb") is not None else tl_all_d
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
            bodyweight_trend=bodyweight_trend,
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
