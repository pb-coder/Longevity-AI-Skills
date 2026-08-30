# Health Export Kit — source spec

**Status:** accepted, not yet implemented
**Date:** 2026-08-30
**Replaces:** Health Auto Export (HAE), both the JSON and the deprecated localized-CSV reader
**Implementation plan:** `Skills/docs/superpowers/plans/2026-08-30-health-export-kit-importer.md`

---

## 1. Why

Health Auto Export stopped producing usable exports after the iOS 27 update. The last
successful import was **2026-08-23** for <Person> and **2026-08-10** for <OtherPerson>.

The replacement is an iOS app called **Health Export Kit**. It writes a single JSON file
covering a user-chosen date range. It is a different format from HAE in every respect —
not a variant, a rewrite.

This document records what the format contains, what was verified against existing tracker
data, the rules the importer must apply, and the decisions taken. It is the source of truth
for the implementation plan.

---

## 2. Source format

```
app            "Health Export Kit"
appVersion     "1.0.13"   (the second tracker's phone was on 1.0.12; no schema difference observed)
schemaVersion  1
mode           "json"
```

Top level: `meta`, `activity`, `sleep`, `additional`.

```
meta.rangeStart / rangeEnd / exportedAt   ISO 8601 UTC with Z
meta.timeZone                             IANA zone, e.g. "Europe/Paris"
meta.categories                           list of REQUESTED categories
meta.notes                                prose describing the export's own conventions

activity.timeZone
activity.totals.{steps, activeEnergyKcal, basalEnergyKcal, distanceKm,
                 exerciseMinutes, flightsClimbed, workoutCount}
activity.daily[]      one row per local day, same keys as totals plus `date`
activity.workouts[]   one row per workout

sleep.sessions[]      one row per sleep session (NOT per night — see §6.4)
sleep.streams.{heartRate, hrvSDNN, oxygenSaturation, respiratoryRate,
               wristTemperature}          sleep-window samples only
sleep.streams.anchor / timeFormat

additional.body        {units, aggregation, daily[]}
additional.heart       {units, aggregation, daily[]}
additional.mobility    {units, aggregation, daily[]}
additional.mind        {units, aggregation, daily[]}
additional.ecg         flat list
additional.stateOfMind flat list
```

Each `additional.*` section carries its own `units` and `aggregation` maps. `aggregation`
values seen: `sum`, `avg`, `latest`. **Read them; do not hardcode.**

### 2.1 Compact vs verbose

The app offers both. **Use compact.** Verified on the same 30-day range:

| | verbose | compact |
|---|---|---|
| File size | 8.2 MB | 436 KB |
| Sleep sessions | — | byte-identical to verbose, all 30 |
| Workout summary fields | — | identical on every workout |
| Splits | present | present |
| Swim `lap` events | present | **present** |
| `segment` events | present | dropped |
| GPS `route` | present | dropped |
| Raw workout `streams` | present | replaced by `perMinute` |
| Sleep HR / respiratory streams | full resolution | 5-minute avg/min/max bins |

Nothing the tracker stores comes from routes, `segment` events, or raw workout streams.
The per-night sleep summaries are computed by the app before downsampling, so the 5-minute
binning does not affect any stored value.

At compact size a full 8-month backfill is 2.7 MB.

### 2.2 Filename

```
health-export-json-<YYYY-MM-DD>-<HHMM>_to_<YYYY-MM-DD>-<HHMM>.json
```

Discovery glob: `health-export-json-*.json`. The range is readable from the name, but
**always read `meta.rangeStart` / `meta.rangeEnd` for the authoritative range** — the
filename is local wall-clock and the meta fields are UTC.

---

## 3. Verification performed

Everything below was checked against the tracker's own stored CSVs, which came from the
retired HAE and XML importers. This is an independent cross-check, not the pipeline
compared to itself.

Source file: <Person>, compact, 2026-01-01 → 2026-08-30, 242 days, 698 workouts,
235 sleep sessions.

### 3.1 Exact matches

| Field | Result |
|---|---|
| Workout identity (date + start + type) | **663 / 663** stored rows matched, after the §5.1 clock correction |
| Sleep nights, reassembled per §6.4 | Time in bed, first segment start, last segment end: **224 / 224 exact**. Awake time **222 / 222 exact**, segment count **216 / 216 exact** (the rest are blank in storage). Sleep total, core, deep and REM are exact on 215-220 of 224 and within **0.01 h on every night** — see §3.3. |
| Resting HR | 225 / 225 |
| Walking HR | 225 / 225 |
| Bodyweight | 79 / 79 |
| Waist | 7 / 7 |
| Swim lap counts | 17 / 17 swims, counts identical to `swimming/*.laps.csv` |
| Respiratory rate (sleep vitals avg vs stored daily) | matched to 0.1 |
| Active energy | 37 / 39 |
| Basal energy | 36 / 39 |

The energy mismatches are the two partial edge days (§5.2), not errors.

### 3.2 Known, explained differences

| Field | Result | Cause |
|---|---|---|
| Steps | **0 / 39 match**, export always 2–10% lower | Export de-duplicates overlapping iPhone/Watch samples and matches the Health app. HAE summed both. The export is correct; the stored history is inflated. |
| VO2max | 123 / 162 match, others differ ~0.3 | HAE took the day's last reading; export averages the day. |
| HR recovery | 106 / 115 match, others differ <1 bpm | HAE took the day's max; export averages, and rounds to whole bpm. |
| Exercise minutes | 216 / 225 match | 7 of the 9 mismatches sit in the pre-DST window and are day-boundary spill (§5.1). Two are genuine small aggregation differences. |
| Workout average HR | differs by >2 bpm on 13 of 93 August workouts, max 13.4 | Export uses HealthKit's own workout average; HAE used a windowed series. Checked against the raw per-second HR stream: the export is **closer** (mean absolute error 0.70 bpm vs 1.40). No regression. |

| Workout duration | 601 of 663 exact; the rest differ by exactly 0.10 min | Rounding path. |
| Workout distance | 656 of 663 agree; 7 differ by real amounts | Genuine per-source measurement differences. |

### 3.3 The one residual difference

Sleep total, core, deep and REM match the stored history exactly on 215 to 220 of 224 nights
and differ on the rest by **exactly 0.01 h — one unit in the last decimal place of a
two-decimal hour, 36 seconds.** Nothing differs by more.

The cause is the rounding path, not the grouping. The retired importer reached hours through
the source's own pre-rounded hour values; this one sums seconds and rounds once at the end.
On a handful of nights the underlying seconds sit within a few seconds of a 36-second
boundary and land on the other side of it.

This is recorded rather than corrected. Rounding to match the old path would mean
reproducing a less accurate intermediate step, and 36 seconds on a seven-hour night is
0.14%. It is stated here so nobody later reads "224 / 224" as exact equality on every
column — an earlier draft of this document did claim that, and it was wrong.

### 3.4 Not verified

- The §5.1 clock correction is validated against **one** DST transition (2026-03-29,
  CET→CEST). The October transition is untested. The importer carries a guard
  for it (§5.1).
- the second tracker's backfill file had not been produced when this spec was written. Everything
  about <OtherPerson> below is inferred from his 30-day export.
- The existing HAE importer was never run against these files.
- Whether the app can export data recorded before the app was installed was not tested
  in isolation; the January-to-March data in the backfill predates heavy use and came
  through complete, which is strong but indirect evidence.

---

## 4. Field map

### 4.1 `health_metrics.csv`

| Column | Source | Notes |
|---|---|---|
| `Date` | `activity.daily[].date` | |
| `Bodyweight (kg)` | `additional.body.daily[].values.bodyMass` | `aggregation: latest` |
| `VO2max` | `additional.heart…vo2max` | `avg`; differs slightly from history |
| `Resting HR` | `additional.heart…restingHR` | exact match |
| `HRV SDNN` | **no source — stop writing** | see §7.1 |
| `Sleep HRV SDNN` | **new column**, `sleep.sessions[].vitals.hrvSDNN.avg` | see §7.1 |
| `Walking HR` | `additional.heart…walkingHR` | exact match |
| `HR Recovery 1min` | `additional.heart…hrRecovery` | |
| `Sleep Total` | night's summed `asleepSec` | §6.4 |
| `Sleep Deep` / `Sleep REM` | summed `asleepDeep` / `asleepREM` stage durations | |
| `Time in Bed` | night span, first start to last end | §6.4 |
| `Resp Rate` | `sleep.sessions[].vitals.respiratoryRate.avg` | matches history; HAE's "daily" value was already sleep-only |
| `Wrist Temp` | `sleep.streams.wristTemperature` | effectively empty, see §7.2 |
| `Sleep Breath Dist` | `additional.heart…breathingDisturbances` | **shift +1 day**, see §5.3 |
| `Exercise Min` | `activity.daily[].exerciseMinutes` | |
| `Waist (cm)` | `additional.body…waist` | |
| `Body Fat %` / `Lean Mass (kg)` | no source | already 0/54 populated; no practical loss |
| `Steps` | `activity.daily[].steps` | de-duplicated, see §3.2 |
| `Active Energy (kcal)` | `activity.daily[].activeEnergyKcal` | already kcal, no kJ conversion |
| `Basal Energy (kcal)` | `activity.daily[].basalEnergyKcal` | |
| `Daylight (min)` | **new column**, `additional.mind…daylight` | `sum` |
| `Mindful (min)` | **new column**, `additional.mind…mindful` | `sum` |

Walking-quality columns (all new, from `additional.mobility`, all `avg` unless noted):
`Walking Speed (km/h)`, `Step Length (cm)`, `Double Support (%)`, `Walking Asymmetry (%)`,
`Stair Speed Up (m/s)`, `Stair Speed Down (m/s)`, `Walking Steadiness (%)` (`latest`),
`Six Min Walk (m)` (`latest`).

### 4.2 `workout_sessions.csv`

| Column | Source |
|---|---|
| `Date`, `Start`, `End` | `start` / `end`, after §5.1 correction |
| `Apple Type` | §4.3 map |
| `Duration (min)` | `durationSec / 60` — pause-excluded active time, matches history |
| `Avg HR` / `Max HR` / `Min HR` | `averageHeartRateBpm` / `maxHeartRateBpm` / `minHeartRateBpm` |
| `Active Cal (kcal)` | `activeEnergyKcal` |
| `Distance (km)` | `distanceKm` |
| `Source` | `source`, normalized. **Two cautions.** The string carries a U+00A0 non-breaking space inside "Apple Watch" and must be normalized — write the `\u00a0` escape, never the literal character, which does not survive transcription and cannot be reviewed. Separately, the column changes meaning: the retired importer wrote the constant `HealthAutoExport`, this one passes the device name through, so 661 of 663 rows differ on this column alone. |
| `Incidental` | existing tracker logic, unchanged |

### 4.3 Workout type map — verified on 663 rows, no unmapped combinations

| export `type` | `isIndoor` | stored `Apple Type` | n |
|---|---|---|---|
| Walking | false | `Walking` | 432 |
| Walking | true | `IndoorWalking` | 2 |
| Strength Training | false | `TraditionalStrengthTraining` | 59 |
| Functional Strength | false | `FunctionalStrengthTraining` | 51 |
| Core Training | false | `CoreTraining` | 24 |
| Running | true | `IndoorRunning` | 24 |
| Running | false | `Running` | 4 |
| Swimming | false | `Swimming` | 20 |
| Swimming | true | `Swimming` | 7 |
| Cycling | false | `Cycling` | 17 |
| Cycling | true | `IndoorCycling` | 3 |
| HIIT | false | `HighIntensityIntervalTraining` | 10 |
| Hiking | false / absent | `Hiking` | 6 |
| Rowing | true | `Rowing` | 4 |

`isIndoor` may be **absent** (1 of 698 workouts). Treat absent as `false` for mapping. Do not
use it for swim location at all — see §7.3.

Unknown export types must fall through to `type.replace(" ", "")` and still be stored, the
way the HAE importer handled unknown types.

### 4.4 `swimming/YYYY.MM.workouts.csv`

| Column | Source |
|---|---|
| `Laps` | count of `events[].type == "lap"` — **verified exact on 17 swims** |
| `Location` | **no reliable source — do not write it.** See §7.3. |
| `Duration`, `Distance`, `Avg HR`, `Active Cal` | workout summary fields |
| `Pool Length (m)`, `Strokes`, `SPL`, `Water Temp (°C)` | **no source**, see §7.3 |
| `Avg SWOLF`, `Stroke Mix` | no source, already permanently blank |

`swimming/YYYY.MM.laps.csv` gains lap start/end/duration. It does **not** gain stroke style
or SWOLF — the export's lap events carry only `{start, end, type}`.

### 4.5 New store: sleep architecture

Per-night hypnogram, one row per stage interval:
`Date, Segment #, Stage, Start, End, Duration (min)`.
Stage values seen: `asleepCore`, `asleepDeep`, `asleepREM`, `awake`.

Per-night vitals, from `sleep.sessions[].vitals`, for each of `heartRate`, `hrvSDNN`,
`oxygenSaturation`, `respiratoryRate`: `min`, `avg`, `max`, `p50`, `p90`, `count`, plus
`byStage` averages.

Storage location and file naming follow the existing `sleep/YYYY.MM.*.csv` convention.

### 4.6 New store: per-workout time in zone

From `perMinute[]` (`minute`, `avgHeartRateBpm`, `avgCadenceSPM`, `avgPowerW`,
`distanceMeters`, `paceSecPerKm`). Bucket each minute's average HR into Z1–Z5 using the
existing heart-rate-reserve formula in `Skills/workout-coach/lib/cardio.py`, and store
minutes per zone per workout. This replaces today's estimate, which buckets a whole
session from its single average HR.

`perMinute` is absent on 36 of 698 workouts; `averageHeartRateBpm` is absent on 38. Both
must degrade to blank, never to zero.

---

## 5. Traps

Each of these produces a plausible-looking wrong number if ignored.

### 5.1 Timestamp clock shift (**blocking for backfill**)

Workout and sleep timestamps use `MM-dd HH:mm:ss` with no year, anchored at the range
start. Every timestamp dated before the local DST transition comes out **one hour earlier
than its true local time**. After the transition it is correct.

Evidence: all 155 stored workouts in 2026-01-01 → 2026-03-28 matched an export workout
exactly one hour off with identical duration and type; sleep sessions shifted identically;
the median bedtime read exactly one hour earlier in the export than in the stored history
for every month before the transition, and identical in every month after it. A person does
not move their bedtime by exactly an hour for three months and move it back precisely on
the changeover date; the stored history is right.

**Root cause is not established.** The observed offsets do not fit any single simple
timezone bug. The correction below was fitted to the symptom and then validated.

```
correction = utcoffset(meta.timeZone, at meta.exportedAt)
           - utcoffset(meta.timeZone, at the timestamp's own naive local date)
true_local = exported_naive + correction
```

**Validated:** 663 / 663 stored workouts match exactly, and all 224 sleep nights land on the
right date with exact start and end times, after applying it. Validated against one transition only (§3.4).

**Guard:** the importer must assert that the correction resolves to a whole number of
hours and is within ±2 hours, and refuse the import with a clear error otherwise. This
bounds the correction; it does **not** detect an app that has been fixed. If a future
version changes the defect into something that is not a whole number of hours, or larger
than two, the import fails loudly. If a future version *fixes* it, the guard stays silent:
an export taken in summer over a winter range still yields exactly +1:00, passes both
checks, and shifts every pre-transition stamp an hour the wrong way — the same silent
corruption, inverted. That is a known limitation of this design. The symptom is imported
timestamps disagreeing with the tracker's stored history by an hour in the *opposite*
direction from the original bug; the correction then has to be removed by hand.

The shift also moves **daily totals**, not just timestamps — activity near local midnight
lands on the wrong day. 7 of 78 pre-transition days show this in exercise minutes; the
largest was 34 minutes moving between 27 and 28 February. Daily rows are already bucketed
by the app, so the importer cannot fix this; it is an accepted small inaccuracy in the
January-to-March backfill and must be recorded as such.

### 5.2 Partial edge days

`meta.rangeStart` and `rangeEnd` are timestamps, not dates. The first and last day of any
range are truncated. Two exports 27 minutes apart reported 6,326 and 5,926 steps for the
same 2026-07-31.

**Rule:** write a daily row only when the range fully covers that local day. Sleep is
exempt — the export includes overlapping sessions in full, per `meta.notes`.

Chunked exports must overlap by at least one day so the complete version of a truncated
day arrives in the neighbouring file.

### 5.3 Breathing disturbances day shift

`additional.heart…breathingDisturbances[D]` equals the stored `Sleep Breath Dist[D+1]`.
Tested at offsets −1, 0 and +1: mean absolute error 0.672, 0.649 and **0.168**. The +1
residual is rounding only.

The retired HAE importer had the same rule under a different name
(`SLEEP_ONSET_METRICS` with an 18:00 rollover). **Shift +1 day** to stay continuous with
history.

### 5.4 Humidity is ×100

`weatherHumidityPercent` ranges 2,600–8,700 across both people. It is basis points, not
percent. Divide by 100. Guard: if the value exceeds 100, divide; otherwise take as-is.
This is an app bug and worth reporting upstream.

### 5.5 Absent keys, not null

- Whole sections are omitted when empty. the second tracker's file has no `ecg` key at all.
- `meta.categories` lists what was **requested**. `nutrition` appeared there with no
  corresponding section, because nothing is logged in Apple Health. Never infer presence
  from `categories`.
- Daily rows omit fields entirely. `activity.daily` for 2026-01-01 has no
  `exerciseMinutes` key.
- `isIndoor` is absent on 1 of 698 workouts.

Every read must use `.get()` and distinguish absent from zero.

### 5.6 the second tracker's stored timestamps are minute-truncated

the second tracker's tracker was still on HAE's deprecated localized-CSV reader, which records
`15:00:00` where the export says `15:00:02`. A re-import keyed on exact start time will
**duplicate every one of his historical workouts**.

**Rule:** when reconciling against existing rows, match on same date, same type, and start
within 60 seconds. Applies to the second tracker's history only; the primary tracker's rows match to the second.

### 5.7 Non-breaking space in `source`

Device names arrive with a U+00A0 non-breaking space between "Apple" and "Watch". Normalize
U+00A0 to a plain space before comparing or storing.

---

## 6. Rules the importer must carry

### 6.1 Year reconstruction

Timestamps carry no year. Take the year from `sleep.streams.anchor` / `meta.rangeStart`,
walk forward through the range, and increment the year whenever `MM-dd` wraps backwards.
A range spanning 31 December silently produces last year's dates otherwise.

### 6.2 Aggregation

Read each section's `aggregation` map rather than hardcoding. Where the export's rule
differs from the stored history's rule (VO2max, HR recovery), the export wins going
forward and the difference is recorded, not corrected.

### 6.3 Units

Already in the units the tracker stores: kcal, km, kg, cm, bpm, ms, %, m/s, minutes.
No kJ conversion, unlike HAE. The only conversion is §5.4.

### 6.4 Sleep night assembly

`sleep.sessions[]` is per session, not per night. Three of 235 nights had two sessions.
Reproduce the retired pipeline's behaviour, verified against stored rows:

1. A session starting at or after **18:00** local belongs to the **following** day's night.
   Verified: a 2026-06-27 20:25 session is stored on the 2026-06-28 night row.
2. Otherwise the night is keyed by the session's **wake date**.
3. All sessions assigned to one night merge. `Sleep Total` is the sum of `asleepSec`.
   `Time in Bed` is the span from the earliest start to the latest end, **including the
   gap between sessions**. `N Segments` is the total stage count across sessions.
   Verified on 2026-06-07: stored total 5.97 h = 3.37 + 2.60, in bed 8.44 h = the full
   23:19 → 07:46 span, 37 segments = 30 + 7.
4. The gap between merged sessions is counted as in-bed but **not** as awake time.
   Verified: stored awake 1.94 h against the sessions' own 109 + 8 minutes.

**Validation:** these four rules were run over all 235 sessions and compared to all 224
stored night rows. Every night is produced, on the right date. Time in bed, first segment
start and last segment end match **exactly on 224 / 224**; awake time on 222 / 222 and
segment count on 216 / 216, which is every night where storage holds a value. The four
stage-derived hour columns are covered in §3.3. The 8 extra nights the export produces are
2026-08-23 onward, which the tracker never imported.

### 6.5 Idempotency

Re-importing an overlapping range must not duplicate or corrupt rows. Workouts key on
(date, start) after §5.1 and §5.6. Daily rows and nights key on date and sparse-merge, as
the existing stores already do.

---

## 7. Losses against the old source

### 7.1 Daily HRV — the only loss that costs anything

The export has no all-day HRV. HRV appears only inside sleep: 101 readings across 30
nights, 2 to 4 a night. Confirmed present after enabling every category the app offers;
this is a limit of the app, not a setting.

The two measurements are not interchangeable. Across 23 overlapping days: stored all-day
mean 44.1 with standard deviation 6.5, sleep-window mean 56.0 with standard deviation
22.7, correlation 0.61.

**Decision (user, 2026-08-30):** add a new `Sleep HRV SDNN` column and stop writing
`HRV SDNN`. History stays intact and honest. The recovery score's HRV signal switches to
the new column with its own baseline. Because the backfill supplies the full history on
the new basis in one pass, the 60-day baseline is populated immediately and there is no
blind period.

### 7.2 Wrist temperature

the primary tracker's file has none. the second tracker's has one reading in 30 days. The column stops being
written. Existing values stay.

The recovery score treats wrist temperature as an optional signal and renormalizes over
whatever is present, so this degrades rather than breaks.

### 7.3 Swim detail, including location

Pool length, stroke count, strokes-per-length and water temperature have no source.
Populated on 17 of 27 historical swims. Lap **timings** are recovered, and lap counts match the
historical per-lap files exactly on all 17 swims that have them; lap **stroke style** and SWOLF
are not recovered, and were already permanently gone.

**`Location` has no usable source either, and an earlier draft of this document was wrong to say
otherwise.** It claimed `isIndoor` decides pool versus open water and called that an improvement.
Measured against the stored history: `isIndoor` **disagrees on 24 of 27 swims** and agrees on 3.
Every one of the six swims it marks indoor carries a GPS route of 39 to 287 points, and a pool
swim does not produce a GPS track — the stored `Open Water` is right and the flag is wrong. The
other 18 disagreements are stored as `Outdoor Pool`, a third value a two-way boolean cannot
express at all.

Because `upsert_swim_workouts` sparse-merges and a non-null incoming value overwrites the stored
cell, writing this column would have rewritten 24 correct values with wrong ones on the first
real import. The importer therefore leaves `Location` unset, which is what the retired importer
did and for the same reason.

`isIndoor` remains reliable for the workout **type** map (§4.3), where it was verified on 663
workouts with every pair matching. It is unreliable specifically for swims.

### 7.4 Workout average heart rate, on about 5% of workouts

38 of 698 workouts in the reference export carry no `averageHeartRateBpm` at all, and 34 of
those correspond to stored rows that had one. The retired importer filled them by averaging a
top-level heart-rate series across the workout's window; this format exposes only Apple's own
per-workout statistic, which is simply absent on those workouts.

Recovery from `perMinute` does not work: only 2 of the 38 carry that series, and only 1 has
usable values. No workout gains a heart rate in the other direction.

This matters more than 5% suggests. Average heart rate drives TRIMP, and
`Skills/workout-coach/lib/cardio.py` skips any session missing it, so those sessions contribute
zero training load rather than an approximate amount. 26 of the 38 are short walks, but 12 are
real sessions: 5 strength, 3 swims, and one each of hiking, rowing, HIIT and cycling.

Recorded as a documented gap. The plausible mitigation — having the coach estimate from a
session's own zone data rather than dropping it — is coach logic, not importer logic, and
belongs to a later plan.

### 7.5 Body fat and lean mass

No source, and already 0/54 populated. No practical loss.

---

## 8. Gains

- **Sleep architecture.** Full stage intervals with start and end. `PROJECT.md` currently
  states this is permanently unrecoverable; that is now false and the doc must be
  corrected. `N Segments` matched stored values exactly on all 14 nights that still had
  them, and stopped being populated by HAE after 2026-08-15.
- **the second tracker's missing half.** Steps, active and basal energy, sleep timestamps, time in
  bed, sleep efficiency and segment counts are all zero across his entire stored history
  and all present in the export. This closes the partner export gap and unblocks TDEE and
  the Sleep Regularity Index for him.
- **Per-session sleep vitals** with min/avg/max/p50/p90 and per-stage breakdowns for heart
  rate, HRV, SpO2 and respiratory rate.
- **Measured time in zone** from `perMinute`, replacing an estimate from a single average.
- **Per-km splits** with average and max HR, cadence and power.
- **ECG.** 13 readings, all sinus rhythm. Also listed as a permanent loss in `PROJECT.md`.
- **Time in daylight** (209 of 213 days) and **mindful minutes** (11 days).
- **Walking steadiness** and **six-minute walk distance**, which HAE never provided.
- **Minimum HR, weather, indoor flag** per workout.
- **Basal energy per workout**, present on 664 of 698. HAE's `totalEnergy` was missing on
  roughly 40% of workouts.
- **State of mind**: 3 entries with valence, mood labels and associations. Recorded here
  for completeness; no store is planned.
- **Height**: 1 reading.

---

## 9. Decisions taken

| Decision | Choice | Who |
|---|---|---|
| Export shape | Compact | Claude, from the §2.1 diff |
| Backfill scope | Full history, both people, from first tracked day | User |
| <Person> range | 2026-01-01 → present (tracking starts 2026-01-10) | Claude |
| <OtherPerson> range | 2026-03-01 → present (tracking starts 2026-04-01) | Claude |
| Daily HRV | New `Sleep HRV SDNN` column, stop writing `HRV SDNN` | User |
| New stores | Sleep architecture, time in daylight, per-workout time in zone, walking quality | User |
| Clock shift | Correct in the importer, validated against stored history | User said not to block on it; Claude implemented and verified |
| Steps discontinuity | Resolved by the backfill — the whole series moves to the de-duplicated basis | Claude |

---

## 10. Open items

1. **the second tracker's backfill file** has not been produced. Request: compact,
   2026-03-01 → present.
2. **The humidity ×100 bug** should be reported to the app author, along with the
   timestamp shift in §5.1.
3. **`PROJECT.md` and `CLAUDE.md` claims to correct** once implemented: sleep segments
   are recoverable, ECG is available, `N Segments` is no longer permanently blank, and
   the source-capability flags need a new `health_export_kit` entry.
4. **Accepted and deliberately left**, after the final whole-branch review triaged them:
   - `resolve_year`'s 29-February-in-a-non-leap-year branch has no test. Only reachable on garbage
     input, where refusing is the correct behaviour.
   - `SUM_METRICS` lists `distanceKm`, `flightsClimbed` and `workoutCount`, which `ACTIVITY_FIELDS`
     does not map. Inert — the coverage gate only fires for mapped keys — and they document which
     export fields are sums.
   - `hek_canonical_type` tests `if mapped:` rather than `is not None`. No map value is falsy.
   - Nothing refuses an export whose range lies in the future. A 2027 export writes future-dated
     rows. Windowed coach reads ignore them; latest-of-day reads would not.
5. **`Source` changes meaning, and it is a product decision.** The retired importer wrote the
   constant `HealthAutoExport`; this one passes the device name through, so 661 of 663 rows differ
   on that column alone. Worth settling before a backfill rewrites the history.
6. **Two exports present at once is an unresolved contradiction.** `resolve_export` takes the newest
   by modification time and deletes only that file, so a second export survives to be imported on
   the next `/log`, under whatever `--person` that run resolves. `workout-logger/SKILL.md` step 6
   says always run and never prompt; `workout-logger/references/common-mistakes.md` says stop and
   ask when ownership is ambiguous, and notes a cross-person import is **not** self-healing because
   sparse merge will not undo it. Those two instructions disagree. Resolve before the first import
   with both people's exports in the folder.
7. **Two stray 2023 bodyweight rows** in the primary tracker's `health_metrics.csv` were entered by
   hand and are out of every export range. Leave them alone.
