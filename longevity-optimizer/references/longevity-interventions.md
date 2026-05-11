# Longevity Intervention Reference

## How to Use This File

This file stores the **user's current status** on known interventions.
It does NOT rank, score, or assess them. All prioritization, evidence grading,
and gap analysis must be generated dynamically by searching current literature
at query time.

**When asked to prioritize or rank interventions:**
1. Search for current systematic reviews, meta-analyses, and RCTs
2. Apply the evaluation framework below
3. Cross-reference the user's status column to identify gaps
4. Generate a ranked output grounded in that search — not this file

---

## Evaluation Framework (apply at query time)

### Evidence Tiers — assign per intervention after searching

| Grade | Criteria |
|---|---|
| Established | Replicated RCTs or large prospective cohorts with consistent mechanistic support |
| Promising | Preliminary RCTs or strong observational data; mechanism plausible but effect size uncertain |
| Speculative | Animal data or single-study human signal; insufficient to guide decisions without caveats |
| Insufficient | No credible human data; mechanistic hypothesis only |

Do not pre-assign grades. Grade each intervention fresh from search results.

### "Longevity Optimal" vs Clinical Normal

Standard clinical ranges flag disease. Longevity-optimal targets aim for the
range associated with the lowest all-cause or disease-specific mortality in
long-term population studies — which is often a narrower, more demanding band.

**How to apply this distinction:**

Always search for the current evidence when specific targets are needed. The
principle is: cite the study or population cohort the target derives from, not
a generic number.

**Illustrative examples (not prescriptive — verify against current literature):**

- Fasting glucose: Clinical normal is <100 mg/dL. Some longevity-focused
  analyses of large cohorts suggest risk begins rising above ~85-90 mg/dL —
  cite the specific study if recommending a tighter target.
- Ferritin: Clinical sufficiency may be flagged at >12 ng/mL. Longevity
  analyses sometimes suggest higher depot iron correlates with worse outcomes
  and optimal range is narrower — again, cite source when making this argument.
- VO2 max: Not a standard clinical marker at all, yet consistently the
  strongest quantitative predictor of all-cause mortality in large prospective
  cohorts. Longevity framing elevates it above lipid panels in practical
  priority — search for current percentile tables by age/sex when advising.

The pattern: longevity-optimal framing shifts targets based on outcomes
research rather than disease-threshold logic. Always name the evidence source.

### Priority Weighting (apply dynamically)

When ranking interventions for a user, weight by:
1. Effect size for all-cause mortality or healthspan extension
2. Evidence grade (above)
3. Current gap — load from `<Person>/data/longevity/interventions.md` (intervention status tracker section)
4. Feasibility given user context — load `profile.md` (identity, constraints, location) and `state.md` (current conditions, medications) for the personal lens
5. Cost and reversibility

---

## Clinical Recommendation Principle

Follow current clinical guidelines as the floor, not the ceiling.

**Example of how to apply this:**
If a guideline body (e.g., ESC, AHA, ESCMID) recommends monitoring eGFR every
3 months for tenofovir users, that is the minimum. Longevity framing may
suggest additional markers (cystatin C, urine ACR) not in the standard
protocol — but always anchor to the guideline first, then argue for additions
with cited evidence.

When guidelines conflict or are outdated relative to recent RCTs, flag the
conflict explicitly rather than silently preferring one.

---

## User Status Tracker

The per-user intervention status (DONE / PARTIAL / MISSING / EXPERIMENTAL)
lives in `<Person>/data/longevity/interventions.md` under the
"Intervention status tracker" section. Load that to identify gaps before
generating a priority ranking.
