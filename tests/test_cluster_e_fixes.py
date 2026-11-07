"""Tests for Cluster E bug fixes: E3, E6, E15, E16, E20.

All data is synthetic — no real per-person data.
"""
from __future__ import annotations

import sys
import os
import unittest
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[1]
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))


# ---------------------------------------------------------------------------
# E3: render crash on empty cardio window
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# E6: ### subsection headings zero out sets beneath them
# ---------------------------------------------------------------------------

from workout_coach.lib.plan_validators import count_working_sets_per_workout


class E6SubsectionHeadingTests(unittest.TestCase):
    """E6: count_working_sets_per_workout resets scope on ANY heading,
    including ### Accessories, zeroing out sets that follow."""

    def test_subsection_heading_does_not_reset_workout_scope(self):
        """Sets under a ### Accessories heading still count under Workout A."""
        plan = """# Workout plan — 2026-01-15

## Workout A: PUSH
- Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8 /// 50kgx8

### Accessories
- Cable Lateral Raise: 14kgx12 /// 14kgx12

"""
        counts = count_working_sets_per_workout(plan)
        # 3 bench + 2 lateral = 5; ### heading must NOT reset scope
        self.assertEqual(counts.get("Workout A: PUSH"), 5)

    def test_section_level_2_non_workout_still_resets_scope(self):
        """## Cardio (not a Workout heading) must still reset scope so
        cardio bullets never bleed into a prior workout's count."""
        plan = """# Workout plan — 2026-01-15

## Workout 1: PULL
- Cable Lat Pulldown: 65kgx8 /// 65kgx8 /// 65kgx8

## Cardio 1: Intervals
- Work: 5 x 3 min @ HR 165-175bpm (Zone 4-5, ~85% max), 2 min easy
"""
        counts = count_working_sets_per_workout(plan)
        self.assertEqual(counts.get("Workout 1: PULL"), 3)
        self.assertNotIn("Cardio 1: Intervals", counts)

    def test_deep_heading_h4_does_not_reset_scope(self):
        """#### level headings (h4) also must not reset workout scope."""
        plan = """# Workout plan — 2026-01-15

## Workout B: LEGS
- Barbell Back Squat: 80kgx5 /// 80kgx5

#### Finishers
- Romanian Deadlift: 70kgx10 /// 70kgx10 /// 70kgx10

"""
        counts = count_working_sets_per_workout(plan)
        # 2 squat + 3 rdl = 5
        self.assertEqual(counts.get("Workout B: LEGS"), 5)


# ---------------------------------------------------------------------------
# E15: Freshness hero renders blank big-number when TSB is None
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# E16: NEAT card renders half-empty on empty/all-zero window
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# E20: freshness_scale colors TSB = -5.0 in the wrong band
# ---------------------------------------------------------------------------





if __name__ == "__main__":
    unittest.main()
