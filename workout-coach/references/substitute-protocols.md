# Historical session recommendations

The dated tracker diagnostic and `check_plan.py` still support historical plans. The [weekly coach](../SKILL.md) uses a separate planning workflow.

| Tier | Meaning in a dated tracker snapshot |
| --- | --- |
| A | Rest recommendation based on the historical daily gate. |
| B | Reactive deload or a recovery-session recommendation. |
| C | Modified strength. A downgrade scales the first slots through `expected_rebound_by_session`. The `hold_load` label keeps the full set budget. |
| D | Normal strength. |
| E | Normal strength with high logged freshness. A gap in recorded activity can affect this estimate. |

`load_policy` controls the old load recommendation separately from the label. Full-block deloads reduce the set budget and soften some volume checks. `--override-gate` reproduces an explicit choice to use the full plan and retains the original rationale.

For an existing dated plan, see the [assessment contract](assessment-contract.md). The thresholds live in [constants](../lib/constants.py) and the gate in [health_session_rec.py](../lib/health_session_rec.py).
