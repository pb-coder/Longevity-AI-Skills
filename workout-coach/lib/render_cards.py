"""Compatibility facade for dashboard card renderers.

The card implementation is split by dashboard surface:
- render_cards_today: Today tab and session-call cards
- render_cards_trajectory: Trajectory tab cards
- render_cards_common: shared heading and coach callout helpers

Keep importing from ``render_cards`` in existing scripts; new code should edit
the focused module for the card surface it changes.
"""
from __future__ import annotations



from .render_cards_common import coach_block
from .render_cards_today import (
    card_acwr,
    card_drivers,
    card_hero,
    card_muscle_volume,
    card_neat,
    card_rings,
    card_session_call,
    card_strength,
    card_tier_history_strip,
    card_training_load,
    card_wow,
)
from .render_cards_trajectory import (
    card_behavioral_domain,
    card_body_comp_domain,
    card_cardio_domain,
    card_longevity_score,
    card_metabolic_domain,
    card_nutrition_phase,
    card_recovery_domain,
    card_recovery_practices,
    card_risk_flags,
    card_sleep,
    card_sleep_domain,
    card_swim_trajectory,
    card_vitals,
)

__all__ = [
    "coach_block",
    "card_acwr",
    "card_behavioral_domain",
    "card_body_comp_domain",
    "card_cardio_domain",
    "card_drivers",
    "card_hero",
    "card_longevity_score",
    "card_metabolic_domain",
    "card_muscle_volume",
    "card_neat",
    "card_nutrition_phase",
    "card_recovery_domain",
    "card_recovery_practices",
    "card_rings",
    "card_risk_flags",
    "card_session_call",
    "card_sleep",
    "card_sleep_domain",
    "card_strength",
    "card_swim_trajectory",
    "card_tier_history_strip",
    "card_training_load",
    "card_vitals",
    "card_wow",
]
