"""TSE regular-session clock. Asia/Tokyo. No DST.

A regular session is complete at 15:30 Asia/Tokyo on a TSE trading day
(closing auction). Premarket, regular hours before close, lunch, and
after-hours are not a completed close.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TOKYO = ZoneInfo("Asia/Tokyo")
REGULAR_OPEN = time(9, 0)
REGULAR_CLOSE = time(15, 30)

# JPX cash-equity closures. Weekends are handled separately.
# Source: https://www.jpx.co.jp/corporate/about-jpx/calendar/index.html
TSE_HOLIDAYS = frozenset(
    {
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 12),
        date(2026, 2, 11),
        date(2026, 2, 23),
        date(2026, 3, 20),
        date(2026, 4, 29),
        date(2026, 5, 3),
        date(2026, 5, 4),
        date(2026, 5, 5),
        date(2026, 5, 6),
        date(2026, 7, 20),
        date(2026, 8, 11),
        date(2026, 9, 21),
        date(2026, 9, 22),
        date(2026, 9, 23),
        date(2026, 10, 12),
        date(2026, 11, 3),
        date(2026, 11, 23),
        date(2026, 12, 31),
        date(2027, 1, 1),
        date(2027, 1, 2),
        date(2027, 1, 3),
        date(2027, 1, 11),
        date(2027, 2, 11),
        date(2027, 2, 23),
        date(2027, 3, 21),
        date(2027, 3, 22),
        date(2027, 4, 29),
        date(2027, 5, 3),
        date(2027, 5, 4),
        date(2027, 5, 5),
        date(2027, 7, 19),
        date(2027, 8, 11),
        date(2027, 9, 20),
        date(2027, 9, 23),
        date(2027, 10, 11),
        date(2027, 11, 3),
        date(2027, 11, 23),
        date(2027, 12, 31),
    }
)


def now_tokyo(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=TOKYO)
    if now.tzinfo is None:
        return now.replace(tzinfo=TOKYO)
    return now.astimezone(TOKYO)


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def is_tse_holiday(day: date) -> bool:
    return day in TSE_HOLIDAYS


def is_trading_day(day: date) -> bool:
    return not is_weekend(day) and not is_tse_holiday(day)


def session_phase(now: datetime | None = None) -> str:
    """Clock phase at observation time. Not a price label."""
    current = now_tokyo(now)
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
    """Most recent TSE regular session that has already closed.

    Returns None if no trading day is found within the lookback window.
    """
    current = now_tokyo(now)
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
