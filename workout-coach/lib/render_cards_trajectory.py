"""Compatibility facade for trajectory dashboard cards."""
from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from render_cards_health import card_recovery_practices, card_sleep, card_vitals
from render_cards_domains import (
    card_behavioral_domain,
    card_body_comp_domain,
    card_cardio_domain,
    card_longevity_score,
    card_metabolic_domain,
    card_recovery_domain,
    card_sleep_domain,
)
from render_cards_programs import (
    card_nutrition_phase,
    card_risk_flags,
    card_swim_trajectory,
)

__all__ = [
    "card_behavioral_domain",
    "card_body_comp_domain",
    "card_cardio_domain",
    "card_longevity_score",
    "card_metabolic_domain",
    "card_nutrition_phase",
    "card_recovery_domain",
    "card_recovery_practices",
    "card_risk_flags",
    "card_sleep",
    "card_sleep_domain",
    "card_swim_trajectory",
    "card_vitals",
]
