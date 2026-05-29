"""Shared helpers for dashboard card renderers."""
from __future__ import annotations



from .render_helpers import esc
from .render_validators import auto_wrap_terms


DOMAIN_HEADING_TIPS = {
    "cardiorespiratory": "Your aerobic engine. How efficiently the heart, lungs, and blood vessels deliver oxygen to working muscles. The single strongest longevity predictor across decades of research.",
    "recovery": "How well your nervous system is shifting between effort and rest. The signals here predict whether your body can absorb the training you are prescribing it.",
    "sleep": "Both how much sleep you are getting and how consistently. The timing of bedtime and waketime is its own mortality predictor independent of total hours.",
    "body_comp": "How much of your weight is muscle versus fat, especially the visceral fat around the organs. The composition matters more than the bodyweight number alone.",
    "metabolic": "How well your body processes glucose, lipids, and insulin. The early-warning system for cardiovascular and type 2 diabetes risk decades before symptoms.",
    "behavioral": "Daily movement and sleep schedule consistency. Less glamorous than peak performance numbers, but consistency is what compounds over decades.",
    "risk_flags": "Active conditions, medications, family history, and personalised monitoring items pulled from your longevity profile.",
    "longevity_score": "A composite score across ten longevity-relevant signals. Bloodwork is not yet included; the score is honest about what it does not see.",
}


def _heading(label, key):
    """Wrap a domain heading in a tooltipped term span."""
    tip = DOMAIN_HEADING_TIPS.get(key, "")
    if not tip:
        return label
    return f'<span class="term" data-tip="{esc(tip)}">{esc(label)}</span>'


def coach_block(text: str | None) -> str:
    """Standard coach callout wrapper."""
    if not text:
        return ""
    return f'<aside class="coach">{auto_wrap_terms(text)}</aside>'
