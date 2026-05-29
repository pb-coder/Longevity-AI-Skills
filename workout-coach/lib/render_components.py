"""Compatibility facade for SVG and HTML dashboard components."""
from __future__ import annotations

from .render_components_domain import (  # noqa: F401
    comparison_strip,
    domain_score_dial,
    risk_flag_pill,
    tier_history_strip,
)
from .render_components_load import build_load_series, load_chart_svg  # noqa: F401
from .render_components_misc import embed_workout_markdown, ring  # noqa: F401
from .render_components_recovery import (  # noqa: F401
    confidence_dots,
    driver_bars,
    freshness_scale,
    metric_hero,
    metric_label,
    metric_tip,
    recovery_scale,
    secondary_metric_row,
    sparkline,
)
from .render_components_volume import muscle_bars  # noqa: F401
