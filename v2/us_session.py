"""US regular-session clock. America/New_York includes DST.

A regular session is complete at 16:00 America/New_York on a NYSE trading day.
Premarket, regular hours before close, and after-hours are not a completed close.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)

# NYSE observed closures. Weekend Saturdays/Sundays are handled separately.
# Source: NYSE holiday schedule (observed dates). Do not treat as a live calendar API.
NYSE_HOLIDAYS = frozenset(
    {
        date(2025, 1, 1),
        date(2025, 1, 20),
        date(2025, 2, 17),
        date(2025, 4, 18),
        date(2025, 5, 26),
        date(2025, 6, 19),
        date(2025, 7, 4),
        date(2025, 9, 1),
        date(2025, 11, 27),
        date(2025, 12, 25),
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    }
)


def now_ny(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=NY)
    if now.tzinfo is None:
        return now.replace(tzinfo=NY)
    return now.astimezone(NY)


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def is_nyse_holiday(day: date) -> bool:
    return day in NYSE_HOLIDAYS


def is_trading_day(day: date) -> bool:
    return not is_weekend(day) and not is_nyse_holiday(day)


def session_phase(now: datetime | None = None) -> str:
    """Clock phase at observation time. Not a price label."""
    current = now_ny(now)
    day = current.date()
    if not is_trading_day(day):
        return "closed"
    clock = current.time()
    if clock < REGULAR_OPEN:
        return "pre_market"
    if clock < REGULAR_CLOSE:
        return "regular_open"
    return "after_hours"


def last_completed_session_date(now: datetime | None = None) -> date | None:
    """Most recent NYSE regular session that has already closed.

    Returns None if no trading day is found within the lookback window.
    """
    current = now_ny(now)
    day = current.date()
    clock = current.time()
    if is_trading_day(day) and clock >= REGULAR_CLOSE:
        return day
    cursor = day - timedelta(days=1)
    for _ in range(14):
        if is_trading_day(cursor):
            return cursor
        cursor -= timedelta(days=1)
    return None
