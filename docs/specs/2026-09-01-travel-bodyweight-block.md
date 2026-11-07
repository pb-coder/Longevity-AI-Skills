# Travel bodyweight mode: unresolved requirements

Historical proposal, not implemented behavior or permission to override checks. Current training guidance is in [detraining-and-minimal-dose.md](../../workout-coach/references/detraining-and-minimal-dose.md) and [no-equipment-training.md](../../workout-coach/references/no-equipment-training.md). Those references preserve the evidence, exercise ladders, coverage limits and furniture safety rules. The catalog contains the supported exercise vocabulary. No trip-specific plan is retained here.

## Proposed scope

Support a temporary 3–4-week maintenance block without a gym or pull-up bar, with optional chair/table/bed/towel/door use. The original request allowed six short 15–20-minute sessions weekly; dates, real equipment, floor surface and available hand loads must be confirmed for any future use. Running is optional. A general equipment-profile system and monthly CSV schema changes were outside scope. A gym becoming available ends the no-gym context.

## Configuration and plan checks to design

- Proposed new profile keys: `training_context` (`travel`/`gym`) and semicolon-separated `available_equipment`. Reuse existing session-count, duration and set-time settings; do not bake one trip's values into defaults.
- Set maintenance priorities explicitly. An empty priority map may invoke the normal emphasis fallback, chasing muscles the room cannot train adequately. Verify actual default behavior before implementing an override.
- Design a travel session classification with a weekly core floor and a proposed 1–2-set session dose; current upper/lower core allocation cannot simply be applied to six short sessions.
- Proposed exceptions requiring explicit design and validation: loaded-flexion floor may become zero without usable hand loads; biceps direct-set floor may become four while retaining two exercises. Do not pad weak self-resisted sets merely to turn a check green. The original triceps design could satisfy its normal floor with two exercises and did not need an exemption.
- Scope any cadence-deload or cardio-gap suppression to the temporary context. Retain the health/recovery gate; travel is not an automatic strength override. Every accepted exception must be named in the saved assessment, with its quality limitation.
- Load increment rules do not apply to unweighted sets; do not fabricate kg. Keep the existing volume-credit rule so historical counts do not change.

## Progression and interpretation

Rep-progressed bodyweight movements could expose best/total reps using existing rows. Rung changes already have distinct exercise names. Isometric holds retain duration and remain outside e1RM/load progression. Real hand loads continue through ordinary analytics. No schema change is proposed.

Counted sets are not proof of equivalent stimulus or strength retention. Low-load hypertrophy findings support the direction of the maintenance inference, not an exact dose. State that travel volume is not load-comparable with gym blocks; do not interpret absent gym-lift e1RM as regression. A return from the block may need an explicit layoff/context-change note and conservative re-entry under the active detraining guidance.

## Unresolved practical decisions

- Confirm travel dates, whether plans refresh weekly or cover the whole trip, and whether small hand loads or bands are actually available. Bands require an intentional catalog/test policy change; a historical exclusion must not be silently bypassed.
- Sliding curls depend on floor friction; Nordic variants require a secure anchor and explicit fall-risk assessment. Furniture/door ratings are unknown: do not convert an assumption into a safety guarantee. Use the active no-equipment reference's hard gates and fallbacks.
- Vertical pull, lateral-deltoid and direct-biceps coverage may remain weak. State gaps rather than imply that formal set counts solve them. Self-resisted curls and towel isometrics are maintenance-at-best for an established trainee.
- Derive any nutrition target from current observed weight; do not assume body-fat or lean-mass readings exist. Optional waist data is a baseline, never invented.
- Implementation would require scoped profile parsing, selection filters, named validation exceptions, bodyweight progression interpretation and regression coverage before activation. Catalog entries must still pass catalog integrity checks. None of these proposed exceptions is active merely because this backlog exists.
