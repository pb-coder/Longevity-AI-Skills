# Response Triggers by Category

Reference this file when a query falls into a defined domain. Apply the domain-specific evaluation framework before responding. **Always pair these triggers with the personal data files** at `<Person>/data/longevity/` — they hold the values to compare against. Without them every "is this dose right for me?" question has no anchor.

---

## Supplements

1. Search current research on the specific compound.
2. Evaluate: mechanism → RCT evidence → safety profile → cost / benefit ratio.
3. Cross-reference `<Person>/data/longevity/interventions.md` for the current stack, doses, and timing.
4. Flag interactions: known drug interactions (check `state.md` for current meds), absorption competition (Ca / Zn / Fe / Mg), timing conflicts.
5. Apply dietary context from `state.md` / `profile.md` (e.g., long-term vegan → chronic phytate exposure suppressing mineral absorption).
6. Note evidence gaps: when blood work is absent (`biomarkers.md` empty for a relevant marker), deficiency status is inferred, not confirmed — say so.

**Hard rule**: Never discuss, question, or challenge the user's creatine protocol if `interventions.md` marks it non-negotiable.

---

## Symptoms

1. Search clinical evidence on the symptom before responding.
2. Differentiate: normal physiological variation vs early pathology.
3. Connect to protocol factors loaded from `interventions.md`: nutrition timing, supplement interactions, training load, stress.
4. For chronic dermatologic conditions logged in `state.md`, treat flares as a potential systemic inflammatory signal — investigate root cause alongside topical management.
5. Flag clearly when blood work is required. Do not speculate around gaps that a CBC or metabolic panel would resolve — point at the panel design in `biomarkers.md` (framework) and the lab history in `<Person>/data/longevity/biomarkers.md`.

---

## Longevity Interventions

1. Search latest research on the proposed intervention.
2. Prioritize by evidence-weighted ROI: established (exercise, sleep, diet quality) → evidence-based supplementation → experimental protocols.
3. Quantify uncertainty with evidence quality labels (see `behavior.md` evidence standards).
4. Adjust for jurisdiction availability — load `profile.md` for `Location`.
5. Challenge any intervention framed as essential that lacks Tier 1 evidence.

---

## Training (longevity / recovery lens — not programming)

1. Verify recommendations against current sports science literature.
2. This skill handles training from a longevity / recovery lens only. Workout programming, volume analysis, and session planning belong to `/coach`.
3. Cross-reference `state.md` for current HRV pattern, VO2max, resting HR, sleep. When recovery or training load is relevant, treat any persistent HRV / RHR drift as worth investigating before drawing conclusions.
4. Cardio zones: if the user uses a non-standard Z2 marker (e.g., nasal-breathing as VT1 proxy), flag the open question (lactate test / CPET would resolve). Don't assert standard zone formulas are wrong without evidence.
5. Prioritize injury prevention, joint health, and long-term structural integrity.
6. Cross-reference `interventions.md` for deload status. The `/coach` tracker emits `deloads` and `auto_deload_candidates`; the longevity skill comments on whether the cadence is appropriate, not on programming the next deload.

---

## Nutrition

1. Search nutritional science databases before making claims.
2. Apply protein targets dynamically: search current recommendations for the user's training pattern + dietary profile (typically 1.6–2.2 g/kg for resistance-trained, vegan athletes need to clear the leucine threshold), then calculate against current bodyweight from `state.md`. Compare to intake recorded in `interventions.md`.
3. Evaluate meal timing relative to training windows and circadian context — pull the actual schedule from `interventions.md`.
4. Account for phytate load in mineral absorption assessments when the diet profile in `state.md` / `interventions.md` warrants it (oat / seed / legume-heavy patterns are high-phytate).
5. Calcium: when calcium is relevant, read the current daily dose from `interventions.md`, search current RDA + any condition-specific guidelines, then evaluate adequacy. Do not assume the answer in advance.
6. Iron: read supplementation status from `interventions.md`. When iron or ferritin is relevant, search current evidence on bioavailability for the user's dietary pattern, then assess. Ferritin status is in `biomarkers.md` (or absent — flag the gap).

---

## Skincare and Dermatology

1. Search dermatological research before evaluating.
2. Evaluate evidence-based efficacy for each active ingredient in the user's current routine (load from `interventions.md`).
3. Retinoid / vitamin C / sun exposure interactions: confirm correct alternating schedule and consistent SPF use against the routine in `interventions.md`.
4. Connect zinc supplementation to skin barrier function and any logged dermatologic conditions in `state.md` — zinc deficiency is a known exacerbating factor for atopic conditions.
5. Topical corticosteroids: appropriate for short flare management. Flag if flare frequency or duration appears to be increasing (suggests inadequate barrier maintenance or systemic trigger).
6. Investigate systemic contributors to chronic dermatologic conditions: stress (HRV suppression in `state.md` is a proxy), dietary factors, sleep disruption.

---

## Biomarkers and Blood Work

Load `references/biomarkers.md` (framework: panel design, interpretation principles) plus `<Person>/data/longevity/biomarkers.md` (history). The framework contains no pre-coded ranges — look up current evidence at query time and apply against the user-specific context from `state.md` / `profile.md`.

---

## Circadian and Sleep

1. Load `state.md` for current sleep duration, score, and HRV pattern.
2. HRV suppression is the most informative signal for systemic stress load.
3. Daylight lamp use at high latitudes: evaluate lux level and timing (load `profile.md` for `Location`).
4. Cold exposure: gradual duration increase is reasonable; evidence for longevity benefit is currently preliminary — say so.
