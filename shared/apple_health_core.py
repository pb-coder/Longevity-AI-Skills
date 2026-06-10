"""Small Apple Health parsing primitives shared by import modules."""
from __future__ import annotations

import re
from datetime import datetime

_DT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})(?: ([+-]\d{4}))?"
)


def parse_apple_dt(s):
    """Return (date_str, datetime) from an Apple Health timestamp.

    Keeps the timezone offset when Apple provides one so elapsed-duration
    arithmetic across DST transitions is correct. The returned date string
    remains the Health app's local wall-clock date for tracker bucketing.
    """
    if not s:
        return None, None
    m = _DT_RE.match(s)
    if not m:
        return None, None
    d = m.group(1)
    if m.group(5):
        dt = datetime.strptime(
            f"{d} {m.group(2)}:{m.group(3)}:{m.group(4)} {m.group(5)}",
            "%Y-%m-%d %H:%M:%S %z",
        )
    else:
        dt = datetime(int(d[:4]), int(d[5:7]), int(d[8:10]),
                      int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return d, dt


def hhmm(dt):
    """Return ``HH:MM:SS`` for a datetime, preserving second-level keys."""
    if dt is None:
        return None
    return f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"


def to_float(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
