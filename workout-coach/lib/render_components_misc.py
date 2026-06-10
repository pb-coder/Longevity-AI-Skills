"""Small shared dashboard components."""
from __future__ import annotations

import re

from .render_helpers import esc

# ---------- ring ----------

def ring(actual, target, label, sub):
    if target and target > 0:
        pct = max(0.0, min(actual / target, 1.0))
    else:
        pct = 0.0
    dash = pct * 100.5
    color = "var(--good)" if (actual or 0) >= (target or 0) else "var(--amber)"
    if target == 0 or target is None:
        color = "var(--muted)"
    val_label = f"{actual} / {target}" if target is not None else str(actual)
    return f'''
<div class="ring-wrap">
  <svg class="ring" viewBox="0 0 36 36">
    <circle cx="18" cy="18" r="16" fill="none" stroke="var(--track-bg)" stroke-width="3"></circle>
    <circle cx="18" cy="18" r="16" fill="none"
            stroke="{color}" stroke-width="3"
            stroke-dasharray="{dash:.1f} 100.5"
            stroke-linecap="round" transform="rotate(-90 18 18)"></circle>
  </svg>
  <div class="ring-value">{esc(val_label)}</div>
  <div class="ring-label">{esc(label)}</div>
  <div class="ring-sub">{esc(sub)}</div>
</div>
'''

# ---------- workout markdown embed ----------

def embed_workout_markdown(md_text: str) -> str:
    """Embed the raw markdown into a script tag so inline JS can render
    it on the Workout tab. The .md file remains the source of truth on
    disk; this is for in-browser viewing only."""
    safe = re.sub(r"</script", r"<\\/script", md_text, flags=re.IGNORECASE)
    return f'<script type="text/markdown" id="workout-md">{safe}</script>'
