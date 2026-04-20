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
4. Apply user-specific context (vegan, PrEP, Berlin latitude, 25M, ~78kg)

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

Follow current clinical guidelines as the minimum frequency. For this user,
PrEP-mandated monitoring (eGFR + creatinine) is already in place. All other
intervals should be derived from current guidelines at query time.

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
| Zinc (serum) | Phytate load; vegan diet |
| Iodine (spot urine) | Kelp source has variable content |
| Omega-3 Index | Algae supplement; absorption unconfirmed |
| Vitamin D (25-OH-D) | 5000 IU supplemented but absorption unconfirmed; Berlin latitude (52°N) |

### PrEP-specific (tenofovir)

| Marker | Profile context |
|---|---|
| eGFR | Nephrotoxicity monitoring; already mandated q3mo |
| Creatinine | PrEP monitoring; 10g/day creatine inflates serum creatinine — flag to lab, use cystatin C when confounded |
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
| LDL-C | Standard lipid panel |
| HDL-C | Standard lipid panel |
| Triglycerides | Banana + oat milk in diet |
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

**Creatine and creatinine:** 10g/day creatine will elevate serum creatinine,
which can falsely suggest kidney impairment. Use cystatin C as an alternative
eGFR marker when creatinine is confounded. Flag this to any GP or lab.

**Vitamin D and Berlin latitude:** Cutaneous synthesis is near-zero
October–March at 52°N. Also note: magnesium is a cofactor for vitamin D
activation. If 25-OH-D comes back low despite supplementation, evaluate
magnesium status before increasing dose.

**Ferritin vs hemoglobin:** Hemoglobin can be normal while ferritin is
depleted. Always request ferritin specifically — many labs only flag hemoglobin.

**Homocysteine and B12:** Serum B12 can be normal while functional deficiency
exists. Homocysteine is a better functional proxy. Elevated homocysteine
despite high-dose methylcobalamin warrants investigation of methylfolate.

**ApoB vs LDL-C:** LDL-C can be misleading in high-HDL, low-TG individuals.
ApoB counts all atherogenic particles directly. Request explicitly if not
included by default.
