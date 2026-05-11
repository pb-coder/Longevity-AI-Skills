# Biomarker Reference

## How to Use This File

This file defines **what to test** and provides a framework for interpreting
results. It does not hard-code optimal ranges. Ranges must be looked up at
query time against current evidence, because:

- "Optimal" varies by assay, lab methodology, and population studied
- Guidelines update; frozen numbers become stale
- Longevity-optimal targets often diverge from clinical normal, and that
  divergence requires a citable source to be defensible

**When interpreting lab results:**
1. Look up current guideline ranges for the marker in question
2. Identify whether a longevity-optimal interpretation exists in the literature
3. Present both: clinical range vs longevity-framing range with source cited
4. Apply user-specific context — load from `<Person>/data/longevity/profile.md`, `state.md`, `interventions.md`, and `biomarkers.md` for current bodyweight, conditions, medications, supplement stack, dietary pattern, latitude, and prior lab history.

---

## Longevity-Optimal Interpretation Principle

Standard clinical labs are designed to detect disease. Longevity-optimal
targets aim for the range associated with lowest long-term mortality risk in
large cohort studies — often narrower and more demanding.

**How to apply this when answering queries:**

Always search for the specific evidence. The framework is:
- What does the guideline say? (floor)
- What does outcomes research suggest is optimal? (longevity target)
- What is the source for that claim? (required — do not state without citation)

**Illustrative examples (verify against current literature before citing):**

- HbA1c: Clinical normal is <5.7%. Some cohort analyses find lowest mortality
  risk at <5.3%. If recommending the tighter target, name the cohort.
- ApoB: Standard guidelines vary by cardiovascular risk tier. Longevity
  framing sometimes uses <70-80 mg/dL as a tighter target based on
  atherosclerosis regression data — cite the specific basis.
- Fasting glucose: Clinical threshold for impairment is >100 mg/dL.
  Some prospective data shows risk rising above ~85-90 mg/dL — cite if used.
- Vitamin D (25-OH-D): Clinical sufficiency is typically >20 ng/mL. Optimal
  supplementation targets are debated; search current meta-analyses for the
  range with the best outcome data in this user's latitude and supplementation
  context.

The pattern: state the clinical benchmark first, then argue for a tighter
target only if citable evidence supports it.

---

## Clinical Monitoring Principle

Follow current clinical guidelines as the minimum frequency. If
PrEP-mandated monitoring (eGFR + creatinine) is in place for this user
(check `state.md` and `profile.md`), that's the floor — all other intervals
should be derived from current guidelines at query time.

**Example:** BHIVA and EACS guidelines specify monitoring cadence for PrEP
users. When advising on lab scheduling, look up the current version of the
relevant guideline rather than applying a frozen schedule.

When advising on lab frequency beyond guideline minimums, argue from evidence
for why a specific marker warrants more frequent monitoring given this user's
profile — don't assume a fixed schedule is perpetually valid.

---

## Marker Panel by Domain

No priority ordering. If asked which markers to test first, generate that
ranking dynamically from the user's current gaps and current evidence.

### Vegan-specific risks

| Marker | Profile context |
|---|---|
| Ferritin | Non-heme iron only; phytate suppression; no iron supplementation |
| B12 (serum + homocysteine) | High-dose supplement; serum alone can miss functional deficiency |
| MMA (methylmalonic acid) | Functional B12 marker; more sensitive than serum B12. Complements homocysteine when both available (Niklewicz et al. 2024 systematic review) |
| Zinc (serum) | Phytate load; vegan diet |
| Iodine (spot urine) | Kelp source has variable content |
| Omega-3 Index | Algae supplement; absorption unconfirmed |
| Vitamin D (25-OH-D) | Supplementation absorption unconfirmed; high-latitude residents (>45°N) see near-zero cutaneous synthesis Oct–Mar |

### PrEP-specific (tenofovir)

| Marker | Profile context |
|---|---|
| eGFR | Nephrotoxicity monitoring; already mandated q3mo |
| Creatinine | PrEP monitoring; high-dose creatine supplementation (≥5 g/day) inflates serum creatinine — flag to lab, use cystatin C when confounded |
| Serum calcium | Supplement dose adequacy; tenofovir reduces bone mineral density |
| PTH | Elevated PTH with normal Ca = functional calcium deficiency |
| DEXA scan | Bone mineral density baseline; relevant for PrEP users |

### Metabolic and Cardiovascular

| Marker | Profile context |
|---|---|
| hsCRP | Systemic inflammation; atopic dermatitis may elevate baseline |
| Fasting glucose | Metabolic baseline |
| HbA1c | Glucose regulation over 3-month window |
| ApoB | Atherogenic particle count |
| Lp(a) | Independent genetic CV risk factor. One-time test is sufficient for lifetime risk stratification; level is largely set by genetics and doesn't move with standard interventions |
| LDL-C | Standard lipid panel |
| HDL-C | Standard lipid panel |
| Triglycerides | Banana + oat milk in diet |
| Fasting insulin | Insulin resistance signal that drifts before HbA1c or fasting glucose. Pair with glucose to compute HOMA-IR when interpretation depends on context |
| GGT | Liver oxidative stress and metabolic dysfunction. Sensitive to alcohol, hepatic iron, fatty liver; useful as a non-specific stress marker alongside ALT |
| Homocysteine | B12/folate functional proxy |

### Hormonal

| Marker | Profile context |
|---|---|
| Total testosterone | Zinc and vegan diet relevant |
| Free testosterone | Total T can be normal with low free T |
| SHBG | High-fiber vegan diet relevant |
| Cortisol (AM) | Weekday HRV pattern relevant |
| TSH | Iodine supplementation and kelp variability relevant |
| IGF-1 | Vegan diet relevant; muscle recovery context |


---

## Interpretation Notes (user-specific, not normative)

**Creatine and creatinine:** High-dose creatine supplementation (≥5 g/day)
elevates serum creatinine, which can falsely suggest kidney impairment. Use
cystatin C as an alternative eGFR marker when creatinine is confounded. KDIGO
2024 Practice Point 1.1.2.1 and Table 8 explicitly endorse cystatin C for
populations where creatinine is unreliable, including high-muscle-mass and
creatine-supplementing athletes. Combined eGFRcr-cys is the preferred
equation when both markers are available. Flag this to any GP or lab,
particularly when prior tenofovir exposure makes accurate renal monitoring
load-bearing.

**Vitamin D and high-latitude residence:** Cutaneous synthesis is near-zero
October–March above ~45°N (e.g., Berlin 52°N, Copenhagen 55°N, Stockholm 59°N). Also note: magnesium is a cofactor for vitamin D
activation. If 25-OH-D comes back low despite supplementation, evaluate
magnesium status before increasing dose.

**Ferritin vs hemoglobin:** Hemoglobin can be normal while ferritin is
depleted. Always request ferritin specifically — many labs only flag hemoglobin.

**Homocysteine and B12:** Serum B12 can be normal while functional deficiency
exists. Homocysteine is a better functional proxy. Elevated homocysteine
despite high-dose methylcobalamin warrants investigation of methylfolate.
MMA (methylmalonic acid) is the most sensitive functional B12 marker and
should be ordered when homocysteine is equivocal or when serum B12 is
inflated by inactive analogues from algae / fortified foods.

**MTHFR variants and COMT balance:** MTHFR polymorphisms reduce conversion of
folate to active methylfolate, contributing to elevated homocysteine. The
standard correction is methylated B12 + methylfolate. A slow COMT pathway can
be overwhelmed by aggressive methyl-donor loading; irritability and anxiety
are the typical flags. When supplementing methylated forms, titrate moderate
to high against homocysteine plus subjective tolerance, not just serum B12.
Evidence tier: Established for MTHFR mechanism; Promising for the COMT
balance framing.

**GGT as a longevity signal beyond hepatobiliary screening:** UK Biobank
(N=293,667, median follow-up 11.8 years) found that men with GGT around 60
U/L, the upper end of the clinical "normal" reference, had hazard ratios of
3.25 (95% CI 2.38-4.42) for liver-related mortality and 1.43 (95% CI
1.27-1.60) for cardiovascular mortality versus the lowest decile (~14.5
U/L). The signal tracks oxidative stress and hepatic insulin resistance, not
just alcohol or biliary disease. When interpreting a "normal" GGT, anchor
to the cohort's lowest decile, not the lab reference ceiling.

**Homocysteine as a longevity signal:** Korean adult male cohort: every 5
μmol/L increase in serum homocysteine elevated all-cause mortality by ~33.6%.
For strict vegans without consistent B12 supplementation, hyperhomocysteinemia
is the dominant preventable longevity risk. The clinical normal ceiling (<15
μmol/L) is permissive; cohort data supports a working target nearer to 10
μmol/L when modifiable causes are addressable.

**Vitamin D plus calcium combined-dose risk:** 5000 IU/day D3 with 900 mg/day
elemental calcium carries hypercalcemia and ectopic vascular calcification
risk over years when not paired with serum calcium monitoring. K2 (MK-7)
directs calcium toward bone and away from arteries but does not eliminate the
hypercalcemia risk from the upstream load. When this stack is in place, serum
calcium and PTH belong in the recurring panel alongside 25-OH-D.

**ApoB vs LDL-C:** LDL-C can be misleading in high-HDL, low-TG individuals.
ApoB counts all atherogenic particles directly. Request explicitly if not
included by default.
