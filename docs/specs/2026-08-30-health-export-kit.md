# Health Export Kit: source-format decisions

Implemented importer: `shared/import_health_export_kit.py`. This reference preserves source quirks and their rationale; executable mappings, current schemas and supported writes are authoritative in the importer and stores. Historical rollout checklists and verification counts are omitted.

## Shape and discovery

A single `health-export-json-*.json` file contains `meta`, `activity`, `sleep`, and `additional`. Supported schema versions are handled by the importer. Prefer compact export: it preserves workout summaries, splits, swim lap events and sleep summaries while dropping routes, segment events and raw workout streams. Sleep streams may be downsampled; app-computed night summaries precede that downsampling.

`meta.rangeStart`, `rangeEnd`, and `exportedAt` are UTC ISO timestamps; `meta.timeZone` is the local IANA zone. Filename dates are local clock values and are not the authoritative range. Default discovery chooses the newest matching file by mtime; explicit `--export` accepts a path or glob. Ownership must be established by the caller's resolved person, not inferred from metrics.

`activity.daily` provides day aggregates; `activity.workouts` provides workouts. `sleep.sessions` is per session, not per night. `additional` sections carry their own `units` and `aggregation` maps (`sum`, `avg`, `latest`). Read those maps. Requested `meta.categories` do not prove a populated section exists. Empty sections and individual fields are often omitted: distinguish absent from zero throughout.

## Time reconstruction and limitations

Source workout/sleep timestamps can use yearless `MM-dd HH:mm:ss`. Reconstruct the year from the source anchor/range, advancing when month-day wraps across New Year.

The original export exhibited a DST-related clock shift. The implemented correction is:

```
correction = offset(zone, exportedAt) - offset(zone, timestamp's local date)
true_local = source_naive + correction
```

The correction was validated against stored workout and sleep history, across one DST transition. Its root cause is unproven. Require a whole-hour correction within ±2 hours; refuse unsupported offsets. This guard cannot detect an app version that fixes the original bug: the old correction could then shift timestamps incorrectly while passing the guard. Opposite-direction hour differences against historical records require reviewing the correction rather than assuming changed behavior.

Daily totals are already bucketed by the app; near-midnight activity misbucketed by that defect cannot be reconstructed from daily aggregates. Write daily records only when the export range fully covers the local day. Adjacent chunks need at least one overlapping day. Sleep sessions overlapping a range boundary are exported in full and are exempt from the daily completeness gate.

Breathing disturbances are onset-date values: shift them forward one day to preserve the tracker wake-date convention. Legacy minute-truncated workout starts require reconciliation by date, type and start within 60 seconds rather than exact seconds; otherwise a refresh duplicates history.

## Units and field pitfalls

- Unit-gate quantities; skip incompatible units rather than invent conversions. Daily quantities are ordinarily kcal, km, kg, cm, bpm, ms, percent, m/s or minutes. Aggregation rules can differ from the retired source; preserve the export's semantics rather than forcing historical equality.
- `weatherHumidityPercent` was observed in basis points. Divide values above 100 by 100; preserve values already in percent.
- Normalize U+00A0 to an ordinary space in device-source names before comparing/storing. Imported device identities differ from the retired constant source label; preserve current typed source semantics.
- Long-range exports can omit `basalEnergyKcal` and report `totalEnergyKcal == activeEnergyKcal`. Accept a total only when basal exists or the total genuinely exceeds active. Otherwise leave total unknown; do not store active energy twice under different meanings.
- Workout average/max/min HR can be absent. Missing imported HR must not erase a stored reading. Never substitute zero or derive a new average from another signal without an explicit policy.
- Unknown workout types still store through the canonical fallback; missing `isIndoor` defaults false for activity-type mapping. It is not reliable evidence of swim location.

## Sleep assembly

1. A session beginning at or after 18:00 local belongs to the following night's date; otherwise use the wake date.
2. Merge sessions assigned to that night. Sum asleep and stage durations; count stage entries across sessions.
3. Time in bed is the span from earliest start to latest end, including inter-session gaps. Those gaps are not additional awake-stage time.
4. Preserve first/last clock times for regularity analysis. Keep manual sleep's sparse merge and manual Notes policy.
5. Nightly respiratory rate weights each available session average by `asleepSec`. If the total asleep weight is not positive, use the plain mean of available session averages; omit the value when none exists.

## Source boundaries and writes

Daily HRV and wrist temperature are not supplied on a comparable all-day basis. Sleep-window HRV has different sampling and variance and must not contaminate the historical daily recovery baseline. Workout effort/RIR, ECG-derived coaching, per-lap stroke style and SWOLF are outside the current import contract. Availability in raw export does not imply an implemented tracker store.

Swim aggregates use summary distance/duration/HR/energy and count `events` of type `lap`. Do not invent pool length, stroke count, SPL, water temperature or location. No new lap CSVs are written; existing detailed lap history remains readable.

Workouts deduplicate by corrected date/start, including legacy start reconciliation; days and nights by date. Daily health, nightly sleep, and swim aggregates sparse-merge missing input without clearing populated values. Workout-session matches replace other imported fields, so missing values can clear them; preserve existing HR when incoming HR is missing, existing Notes when incoming Notes are empty, and an existing Incidental classification when the incoming flag is empty/false. Preserve manual cardio deduplication. Auto-cardio obeys the profile flag and past-month write gate. Successful imports delete the consumed JSON unless `--keep-export` is set, then commit the person's data repository. Git history is the rollback path.
