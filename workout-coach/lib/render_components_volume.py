"""Per-muscle volume dashboard components."""
from __future__ import annotations

from .render_helpers import esc

# ---------- per-muscle bar chart ----------

def muscle_bars(weekly_volume, hr_divergence=None):
    current = weekly_volume.get("current", {})
    landmarks = weekly_volume.get("landmarks", {})
    if not current:
        return ""
    hr_divergence = hr_divergence or {}

    def gap_score(m):
        v = current.get(m, 0.0)
        lm = landmarks.get(m, {})
        mev, mrv = lm.get("mev", 0), lm.get("mrv", 0)
        if v < mev:
            return -2_000 + (mev - v)
        if v > mrv:
            return -1_000 + (v - mrv)
        return v - mev

    muscles = sorted(current.keys(), key=gap_score)[:14]
    xmax = max(
        max(current.values()) if current else 1,
        max((landmarks.get(m, {}).get("mrv", 0) for m in muscles), default=1),
    ) * 1.1 or 1.0

    rows = []
    for m in muscles:
        v = current.get(m, 0.0)
        lm = landmarks.get(m, {})
        mev = lm.get("mev", 0)
        mav = lm.get("mav", 0)
        mrv = lm.get("mrv", 0)
        muscle_title = m.replace("_", " ").title()
        if v < mev:
            band_class = "low"   # orange — under-stimulating, add
            status = "not enough"
            tip = (
                f"{muscle_title}: {v:.1f} sets per week. Below the productive range "
                f"(starts at {mev}). Add 1 to 2 sets next week to enter the productive band."
            )
        elif v <= mav:
            band_class = "prod"  # green — sweet spot
            status = "productive"
            tip = (
                f"{muscle_title}: {v:.1f} sets per week. In the productive range "
                f"({mev} to {mav}). Stay here, or push toward the upper band when recovery permits."
            )
        elif v <= mrv:
            band_class = "push"  # yellow-amber — pushing the limit
            status = "pushing limit"
            tip = (
                f"{muscle_title}: {v:.1f} sets per week. Above the productive range, "
                f"approaching your recoverable ceiling at {mrv}. You can grow here, but fatigue "
                f"costs rise. Watch recovery and don't add more."
            )
        else:
            band_class = "over"  # red — over recoverable ceiling, cut back
            status = "too much, cut back"
            tip = (
                f"{muscle_title}: {v:.1f} sets per week. Above your recoverable ceiling at {mrv}. "
                f"This volume costs more than it gives back. Drop 1 to 2 sets per week."
            )

        # Per-muscle HR-at-volume annotation (was its own block on the
        # strength card — moved here so all per-muscle state lives on
        # one card). Rising HR at constant volume → fatigue (warn); falling
        # HR → improving conditioning (good). Stable / absent → no chip,
        # per DESIGN.md's hide-empty-states rule.
        hrd = hr_divergence.get(m) or {}
        hr_hint = (hrd.get("hint") or "")
        hr_slope = hrd.get("slope_bpm_per_4w")
        hr_html = ""
        if hr_hint.startswith("rising") and hr_slope is not None:
            hr_html = (
                f'<span class="bar-hr warn" data-tip="Rising HR at constant '
                f'volume — fatigue or under-recovery signal.">'
                f'&uarr; +{hr_slope:.1f} bpm/4w</span>'
            )
        elif hr_hint.startswith("falling") and hr_slope is not None:
            hr_html = (
                f'<span class="bar-hr good" data-tip="Falling HR at constant '
                f'volume — improving conditioning.">'
                f'&darr; {hr_slope:.1f} bpm/4w</span>'
            )

        mev_x = (mev / xmax) * 100
        mav_x = (mav / xmax) * 100
        actual_x = (v / xmax) * 100
        rows.append(f'''
<div class="bar-row" data-tip="{esc(tip)}">
  <span class="bar-label">{esc(m.replace("_", " "))}</span>
  <div class="bar-track">
    <div class="bar-tick" style="left:{mev_x:.1f}%" data-label="MEV"></div>
    <div class="bar-tick" style="left:{mav_x:.1f}%" data-label="MAV"></div>
    <div class="bar-fill band-{band_class}" style="width:{actual_x:.1f}%"></div>
  </div>
  <span class="bar-status">
    <span class="bar-dot band-{band_class}"></span>
    <span class="bar-status-label">{esc(status)}</span>
    <span class="bar-num">{v:.1f}</span>
    {hr_html}
  </span>
</div>''')
    return "\n".join(rows)
