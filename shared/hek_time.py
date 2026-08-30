"""Clock, calendar and range primitives for the Health Export Kit format.

Three timestamp shapes appear in one export file:

- ``meta.rangeStart`` / ``rangeEnd`` / ``exportedAt``: ISO 8601, UTC, ``Z``.
- ``activity.daily[].date`` and every ``additional.*.daily[].date``: ``YYYY-MM-DD``.
- Workout, sleep, stage, stream and route stamps: ``MM-dd HH:mm:ss``, no year,
  local to ``meta.timeZone``.

The year-less shape carries two defects the importer must repair.

**The year.** It is only recoverable from the export's own range. A range
spanning 31 December otherwise silently produces last year's dates. We refuse
ranges longer than a year, where ``MM-dd`` is genuinely ambiguous.

**The clock.** Every stamp dated before a daylight-saving transition arrives
exactly one hour early; stamps after it are correct. Verified against the
tracker's stored history: 663 of 663 workouts and 224 of 224 sleep nights
match once corrected, and none match before. The root cause inside the app is
not known, so the correction below was fitted to the symptom and then
validated, and it is bounded by a guard: anything that is not a whole number
of hours within two hours of zero raises rather than shifting real data. A
future app version that fixes the bug will fail loudly here instead of
quietly double-correcting.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MAX_RANGE_DAYS = 366
MAX_CORRECTION = timedelta(hours=2)
# Sessions overlapping the range are included in full, so a stamp may fall
# this far outside it and still be legitimate.
RANGE_SLACK = timedelta(days=2)


class ClockGuardError(ValueError):
    """A timestamp could not be resolved safely. Never guess; refuse."""


def _utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC stamp ending in ``Z`` into an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _zone(meta: dict) -> ZoneInfo:
    return ZoneInfo(meta["timeZone"])


def local_range(meta: dict) -> tuple[datetime, datetime]:
    """Return the export's range as naive local datetimes."""
    tz = _zone(meta)
    start = _utc(meta["rangeStart"]).astimezone(tz).replace(tzinfo=None)
    end = _utc(meta["rangeEnd"]).astimezone(tz).replace(tzinfo=None)
    return start, end


def export_offset(meta: dict) -> timedelta:
    """The zone's UTC offset at the moment the export was taken."""
    tz = _zone(meta)
    return _utc(meta["exportedAt"]).astimezone(tz).utcoffset()


def _check_correction(correction: timedelta) -> timedelta:
    if abs(correction) > MAX_CORRECTION:
        raise ClockGuardError(
            f"clock correction {correction} exceeds the {MAX_CORRECTION} guard; "
            f"refusing to shift timestamps"
        )
    if correction % timedelta(hours=1) != timedelta(0):
        raise ClockGuardError(
            f"clock correction {correction} is not a whole number of hours; "
            f"refusing to shift timestamps"
        )
    return correction


def resolve_year(mmdd: str, meta: dict) -> int:
    """Pick the calendar year a bare ``MM-dd`` belongs to.

    Tries every year the range touches and keeps the one that lands inside
    the range (plus slack). Exactly one must fit; zero or two is a refusal.
    """
    start, end = local_range(meta)
    if (end - start).days > MAX_RANGE_DAYS:
        raise ClockGuardError(
            f"export range spans {(end - start).days} days; MM-dd stamps are "
            f"ambiguous beyond {MAX_RANGE_DAYS}. Export in shorter ranges."
        )
    month, day = (int(p) for p in mmdd.split("-"))
    lo = (start - RANGE_SLACK).date()
    hi = (end + RANGE_SLACK).date()
    hits = []
    for year in range(start.year, end.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue  # 29 February in a non-leap year
        if lo <= candidate <= hi:
            hits.append(year)
    if len(hits) != 1:
        raise ClockGuardError(
            f"cannot resolve a year for {mmdd!r} in range {lo}..{hi}: "
            f"{len(hits)} candidates"
        )
    return hits[0]


def parse_stamp(stamp: str, meta: dict) -> datetime:
    """Parse ``MM-dd HH:mm:ss`` into a corrected naive local datetime."""
    mmdd, hms = stamp.split(" ", 1)
    year = resolve_year(mmdd, meta)
    naive = datetime.strptime(f"{year}-{mmdd} {hms}", "%Y-%m-%d %H:%M:%S")
    tz = _zone(meta)
    correction = _check_correction(export_offset(meta) - naive.replace(tzinfo=tz).utcoffset())
    return naive + correction


def parse_day(value: str) -> date:
    """Parse a ``YYYY-MM-DD`` daily-row date. These carry no clock defect."""
    return date.fromisoformat(value)


def complete_days(meta: dict) -> tuple[date, date]:
    """The inclusive first and last local day the range fully covers.

    ``rangeStart`` and ``rangeEnd`` are instants, not dates, so the first and
    last day of any export are truncated. Two exports 27 minutes apart
    reported 6,326 and 5,926 steps for the same 2026-07-31.
    """
    start, end = local_range(meta)
    midnight = datetime.min.time()
    # A range starting at 00:00:00 covers that day in full; anything later
    # truncates it, so the first whole day is the next one. The end is
    # exclusive either way: a range ending at any time on day D leaves D
    # itself incomplete.
    first = start.date() if start.time() == midnight else start.date() + timedelta(days=1)
    last = end.date() - timedelta(days=1)
    return first, last
