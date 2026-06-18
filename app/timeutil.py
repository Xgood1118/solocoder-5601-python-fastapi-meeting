from datetime import datetime, timedelta, date
from typing import Optional, Tuple
from dateutil import parser


def parse_dt(s: str) -> datetime:
    return parser.isoparse(s)


def to_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def strictly_overlaps(
    start1: datetime, end1: datetime, start2: datetime, end2: datetime
) -> bool:
    s1, e1 = to_naive(start1), to_naive(end1)
    s2, e2 = to_naive(start2), to_naive(end2)
    return s1 < e2 and s2 < e1


def is_adjacent_or_non_overlap(
    start1: datetime, end1: datetime, start2: datetime, end2: datetime
) -> bool:
    return not strictly_overlaps(start1, end1, start2, end2)


def same_day(d: date, dt: datetime) -> bool:
    return to_naive(dt).date() == d


def spans_days(start: datetime, end: datetime) -> bool:
    return to_naive(start).date() != to_naive(end).date()


def add_minutes(dt: datetime, minutes: int) -> datetime:
    return dt + timedelta(minutes=minutes)


def minutes_until(target: datetime, now: Optional[datetime] = None) -> int:
    if now is None:
        now = datetime.now()
    delta = to_naive(target) - to_naive(now)
    return int(delta.total_seconds() // 60)


def validate_range(start: datetime, end: datetime) -> Optional[str]:
    if to_naive(end) <= to_naive(start):
        return "end time must be after start time"
    return None


def clip_to_day(d: date, start: datetime, end: datetime) -> Optional[Tuple[datetime, datetime]]:
    s, e = to_naive(start), to_naive(end)
    day_start = datetime.combine(d, datetime.min.time())
    day_end = datetime.combine(d, datetime.max.time())
    clip_s = max(s, day_start)
    clip_e = min(e, day_end)
    if clip_s >= clip_e:
        return None
    return (clip_s, clip_e)


def is_between(now: datetime, start: datetime, end: datetime) -> bool:
    n, s, e = to_naive(now), to_naive(start), to_naive(end)
    return s <= n < e


def now() -> datetime:
    return datetime.now()
