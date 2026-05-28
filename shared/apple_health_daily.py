"""Daily Apple Health record aggregation."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from apple_health_core import parse_apple_dt, to_float

# Tier 1 and Tier 2 record types consumed from Export.xml. Everything
# else is skipped by the streaming importer.
WANTED_RECORD_TYPES = {
    "HKQuantityTypeIdentifierVO2Max",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
    "HKQuantityTypeIdentifierRestingHeartRate",
    "HKQuantityTypeIdentifierWalkingHeartRateAverage",
    "HKQuantityTypeIdentifierHeartRateRecoveryOneMinute",
    "HKQuantityTypeIdentifierRespiratoryRate",
    "HKQuantityTypeIdentifierAppleSleepingWristTemperature",
    "HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances",
    "HKQuantityTypeIdentifierAppleExerciseTime",
    "HKQuantityTypeIdentifierBodyMass",
    "HKCategoryTypeIdentifierSleepAnalysis",
}

SLEEP_ASLEEP_VALUES = {
    "HKCategoryValueSleepAnalysisAsleepCore",
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
    "HKCategoryValueSleepAnalysisAsleepUnspecified",
}
SLEEP_CORE_VALUE = "HKCategoryValueSleepAnalysisAsleepCore"
SLEEP_DEEP_VALUE = "HKCategoryValueSleepAnalysisAsleepDeep"
SLEEP_REM_VALUE = "HKCategoryValueSleepAnalysisAsleepREM"
SLEEP_UNSPEC_VALUE = "HKCategoryValueSleepAnalysisAsleepUnspecified"
SLEEP_AWAKE_VALUE = "HKCategoryValueSleepAnalysisAwake"
SLEEP_IN_BED_VALUE = "HKCategoryValueSleepAnalysisInBed"


class DayAggregator:
    """Collect per-day metric values during the streaming XML pass."""

    def __init__(self):
        self.bodyweight_kg = {}
        self.vo2max = {}
        self.resting_hr = {}
        self.walking_hr = {}
        self.hr_recovery_1min = defaultdict(float)
        self.hrv_sdnn_acc = defaultdict(lambda: [0.0, 0])
        self.resp_rate_acc = defaultdict(lambda: [0.0, 0])
        self.wrist_temp_c = {}
        self.sleep_breath = {}
        self.exercise_min = defaultdict(float)
        self.sleep_total_min = defaultdict(float)
        self.sleep_core_min = defaultdict(float)
        self.sleep_deep_min = defaultdict(float)
        self.sleep_rem_min = defaultdict(float)
        self.sleep_unspec_min = defaultdict(float)
        self.sleep_awake_min = defaultdict(float)
        self.sleep_in_bed_min = defaultdict(float)
        self.sleep_n_segments = defaultdict(int)
        self.sleep_first_seg_start = {}
        self.sleep_last_seg_end = {}

        self._handlers = {
            "HKQuantityTypeIdentifierBodyMass": self._h_bodyweight,
            "HKQuantityTypeIdentifierVO2Max": self._h_vo2max,
            "HKQuantityTypeIdentifierRestingHeartRate": self._h_resting_hr,
            "HKQuantityTypeIdentifierWalkingHeartRateAverage": self._h_walking_hr,
            "HKQuantityTypeIdentifierHeartRateRecoveryOneMinute": self._h_hr_recovery,
            "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": self._h_hrv,
            "HKQuantityTypeIdentifierRespiratoryRate": self._h_resp_rate,
            "HKQuantityTypeIdentifierAppleSleepingWristTemperature": self._h_wrist_temp,
            "HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances": self._h_sleep_breath,
            "HKQuantityTypeIdentifierAppleExerciseTime": self._h_exercise_min,
            "HKCategoryTypeIdentifierSleepAnalysis": self._h_sleep,
        }

    def _set_latest(self, store, d, dt, value):
        cur = store.get(d)
        if cur is None or dt > cur[0]:
            store[d] = (dt, value)

    def add_record(self, attrib, d_start, dt_start):
        if d_start is None:
            return
        handler = self._handlers.get(attrib.get("type", ""))
        if handler is not None:
            handler(attrib, d_start, dt_start)

    def _h_bodyweight(self, attrib, d, dt):
        v = to_float(attrib.get("value"))
        if v is not None:
            self._set_latest(self.bodyweight_kg, d, dt, v)

    def _h_vo2max(self, attrib, d, dt):
        v = to_float(attrib.get("value"))
        if v is not None:
            self._set_latest(self.vo2max, d, dt, v)

    def _h_resting_hr(self, attrib, d, dt):
        v = to_float(attrib.get("value"))
        if v is not None:
            self._set_latest(self.resting_hr, d, dt, v)

    def _h_walking_hr(self, attrib, d, dt):
        v = to_float(attrib.get("value"))
        if v is not None:
            self._set_latest(self.walking_hr, d, dt, v)

    def _h_hr_recovery(self, attrib, d, _dt):
        v = to_float(attrib.get("value"))
        if v is not None and v > self.hr_recovery_1min.get(d, 0.0):
            self.hr_recovery_1min[d] = v

    def _h_hrv(self, attrib, d, _dt):
        v = to_float(attrib.get("value"))
        if v is not None:
            self.hrv_sdnn_acc[d][0] += v
            self.hrv_sdnn_acc[d][1] += 1

    def _h_resp_rate(self, attrib, d, _dt):
        v = to_float(attrib.get("value"))
        if v is not None:
            self.resp_rate_acc[d][0] += v
            self.resp_rate_acc[d][1] += 1

    def _h_wrist_temp(self, attrib, d, dt):
        v = to_float(attrib.get("value"))
        if v is None:
            return
        d_end, dt_end = parse_apple_dt(attrib.get("endDate"))
        self._set_latest(self.wrist_temp_c, d_end or d, dt_end or dt, v)

    def _h_sleep_breath(self, attrib, d, dt):
        v = to_float(attrib.get("value"))
        if v is None:
            return
        d_end, dt_end = parse_apple_dt(attrib.get("endDate"))
        self._set_latest(self.sleep_breath, d_end or d, dt_end or dt, v)

    def _h_exercise_min(self, attrib, d, _dt):
        v = to_float(attrib.get("value"))
        if v is not None:
            self.exercise_min[d] += v

    def _h_sleep(self, attrib, d_start, dt_start):
        d_end, dt_end = parse_apple_dt(attrib.get("endDate"))
        self._add_sleep(attrib.get("value"), dt_start, dt_end, d_start, d_end)

    def _add_sleep(self, value, dt_start, dt_end, _d_start, d_end):
        if value is None or dt_start is None or dt_end is None:
            return
        minutes = (dt_end - dt_start).total_seconds() / 60.0
        if minutes <= 0:
            return
        if dt_end.hour >= 18:
            bucket = (dt_end.date() + timedelta(days=1)).isoformat()
        else:
            bucket = d_end
        if value == SLEEP_IN_BED_VALUE:
            self.sleep_in_bed_min[bucket] += minutes
            return
        if value == SLEEP_AWAKE_VALUE:
            self.sleep_awake_min[bucket] += minutes
        elif value in SLEEP_ASLEEP_VALUES:
            self.sleep_total_min[bucket] += minutes
            if value == SLEEP_CORE_VALUE:
                self.sleep_core_min[bucket] += minutes
            elif value == SLEEP_DEEP_VALUE:
                self.sleep_deep_min[bucket] += minutes
            elif value == SLEEP_REM_VALUE:
                self.sleep_rem_min[bucket] += minutes
            elif value == SLEEP_UNSPEC_VALUE:
                self.sleep_unspec_min[bucket] += minutes
        else:
            return
        self.sleep_n_segments[bucket] += 1
        if value in SLEEP_ASLEEP_VALUES:
            cur_start = self.sleep_first_seg_start.get(bucket)
            if cur_start is None or dt_start < cur_start:
                self.sleep_first_seg_start[bucket] = dt_start
            cur_end = self.sleep_last_seg_end.get(bucket)
            if cur_end is None or dt_end > cur_end:
                self.sleep_last_seg_end[bucket] = dt_end

    def emit(self, since_date):
        all_dates = set()
        for store in (self.bodyweight_kg, self.vo2max, self.resting_hr,
                      self.walking_hr, self.wrist_temp_c, self.sleep_breath):
            all_dates.update(store.keys())
        all_dates.update(self.hr_recovery_1min.keys())
        all_dates.update(self.hrv_sdnn_acc.keys())
        all_dates.update(self.resp_rate_acc.keys())
        all_dates.update(self.exercise_min.keys())
        all_dates.update(self.sleep_total_min.keys())
        all_dates.update(self.sleep_in_bed_min.keys())

        cutoff = since_date.isoformat() if since_date else None
        for d in sorted(all_dates):
            if cutoff and d < cutoff:
                continue

            def lat(store):
                tup = store.get(d)
                return tup[1] if tup else None

            hrv_sum, hrv_n = self.hrv_sdnn_acc.get(d, [0.0, 0])
            rr_sum, rr_n = self.resp_rate_acc.get(d, [0.0, 0])
            sleep_total_min = self.sleep_total_min.get(d, 0.0)
            sleep_deep_min = self.sleep_deep_min.get(d, 0.0)
            sleep_rem_min = self.sleep_rem_min.get(d, 0.0)
            sleep_in_bed_min = self.sleep_in_bed_min.get(d, 0.0)

            yield {
                "date": d,
                "bodyweight_kg": round(lat(self.bodyweight_kg), 2) if lat(self.bodyweight_kg) is not None else None,
                "vo2max": round(lat(self.vo2max), 2) if lat(self.vo2max) is not None else None,
                "resting_hr": round(lat(self.resting_hr), 1) if lat(self.resting_hr) is not None else None,
                "hrv_sdnn": round(hrv_sum / hrv_n, 2) if hrv_n else None,
                "walking_hr": round(lat(self.walking_hr), 1) if lat(self.walking_hr) is not None else None,
                "hr_recovery_1min": round(self.hr_recovery_1min[d], 1) if d in self.hr_recovery_1min else None,
                "sleep_total_h": round(sleep_total_min / 60.0, 2) if sleep_total_min else None,
                "sleep_deep_h": round(sleep_deep_min / 60.0, 2) if sleep_deep_min else None,
                "sleep_rem_h": round(sleep_rem_min / 60.0, 2) if sleep_rem_min else None,
                "time_in_bed_h": round(sleep_in_bed_min / 60.0, 2) if sleep_in_bed_min else None,
                "resp_rate": round(rr_sum / rr_n, 2) if rr_n else None,
                "wrist_temp_c": round(lat(self.wrist_temp_c), 3) if lat(self.wrist_temp_c) is not None else None,
                "sleep_breath_dist": round(lat(self.sleep_breath), 4) if lat(self.sleep_breath) is not None else None,
                "exercise_min": round(self.exercise_min[d], 1) if d in self.exercise_min else None,
            }

    def emit_sleep_nights(self, since_date):
        all_dates = set()
        all_dates.update(self.sleep_total_min.keys())
        all_dates.update(self.sleep_in_bed_min.keys())
        all_dates.update(self.sleep_awake_min.keys())

        cutoff = since_date.isoformat() if since_date else None
        for d in sorted(all_dates):
            if cutoff and d < cutoff:
                continue

            total_min = self.sleep_total_min.get(d, 0.0)
            core_min = self.sleep_core_min.get(d, 0.0)
            deep_min = self.sleep_deep_min.get(d, 0.0)
            rem_min = self.sleep_rem_min.get(d, 0.0)
            unspec_min = self.sleep_unspec_min.get(d, 0.0)
            awake_min = self.sleep_awake_min.get(d, 0.0)
            in_bed_min = self.sleep_in_bed_min.get(d, 0.0)

            total_h = round(total_min / 60.0, 2) if total_min else None
            in_bed_h = round(in_bed_min / 60.0, 2) if in_bed_min else None
            first_seg = self.sleep_first_seg_start.get(d)
            last_seg = self.sleep_last_seg_end.get(d)
            n_seg = self.sleep_n_segments.get(d, 0) or None

            if in_bed_h is None and first_seg and last_seg and last_seg > first_seg:
                derived = (last_seg - first_seg).total_seconds() / 3600.0
                if derived > 0 and (total_h is None or total_h <= derived + 0.05) \
                        and (total_h is None or total_h >= 2.0):
                    in_bed_h = round(derived, 2)

            efficiency = (
                round(total_h / in_bed_h * 100.0, 1)
                if total_h is not None and in_bed_h is not None and in_bed_h > 0
                else None
            )

            yield {
                "date": d,
                "total_h": total_h,
                "core_h": round(core_min / 60.0, 2) if core_min else None,
                "deep_h": round(deep_min / 60.0, 2) if deep_min else None,
                "rem_h": round(rem_min / 60.0, 2) if rem_min else None,
                "unspecified_h": round(unspec_min / 60.0, 2) if unspec_min else None,
                "awake_h": round(awake_min / 60.0, 2) if awake_min else None,
                "time_in_bed_h": in_bed_h,
                "efficiency_pct": efficiency,
                "n_segments": n_seg,
                "first_segment_start": first_seg.strftime("%Y-%m-%d %H:%M:%S") if first_seg else None,
                "last_segment_end": last_seg.strftime("%Y-%m-%d %H:%M:%S") if last_seg else None,
            }
