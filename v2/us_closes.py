"""Completed US regular-session closes. No live, pre, or post prices."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from v2 import DATA_UNAVAILABLE
from v2.us_session import NY, last_completed_session_date, now_ny

YAHOO_CHART = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2mo"
)
REQUIRED_FIELDS = (
    "symbol",
    "asset_type",
    "price",
    "currency",
    "price_date",
    "observed_at",
    "source",
    "freshness_status",
    "session_status",
)
ASSET_TYPE = "us_equity"


def yahoo_source(symbol: str) -> str:
    return YAHOO_CHART.format(symbol=symbol)


def fetch_daily_bars(symbol: str) -> dict[str, Any] | None:
    """Daily bars only. Ignores regularMarketPrice, preMarketPrice, postMarketPrice."""
    url = yahoo_source(symbol)
    req = urllib.request.Request(url, headers={"User-Agent": "marume-report-v2"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None
    try:
        result = data["chart"]["result"][0]
        meta = result.get("meta") or {}
        quote = result["indicators"]["quote"][0]
        timestamps = result.get("timestamp") or []
        closes = quote.get("close") or []
    except (KeyError, IndexError, TypeError):
        return None
    bars: list[dict[str, Any]] = []
    for ts, close in zip(timestamps, closes):
        if ts is None or close is None:
            continue
        try:
            session_day = datetime.fromtimestamp(int(ts), tz=NY).date()
            close_value = float(close)
        except (OSError, OverflowError, TypeError, ValueError):
            continue
        bars.append({"date": session_day, "close": close_value})
    currency = meta.get("currency")
    return {
        "bars": bars,
        "currency": currency if isinstance(currency, str) and currency else None,
        "source": url,
    }


def select_completed_close(
    bars: list[dict[str, Any]],
    session_day: date,
) -> dict[str, Any] | None:
    """Use the bar whose date equals the completed session. Do not relabel an older bar."""
    for bar in reversed(bars):
        if bar.get("date") == session_day and bar.get("close") is not None:
            return bar
    return None


def unavailable_record(
    symbol: str,
    *,
    observed_at: str,
    source: str,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "asset_type": ASSET_TYPE,
        "price": DATA_UNAVAILABLE,
        "currency": DATA_UNAVAILABLE,
        "price_date": DATA_UNAVAILABLE,
        "observed_at": observed_at,
        "source": source,
        "freshness_status": DATA_UNAVAILABLE,
        "session_status": DATA_UNAVAILABLE,
        "error": DATA_UNAVAILABLE,
    }


def quote_from_bars(
    symbol: str,
    payload: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_at = now_ny(now).isoformat()
    source = yahoo_source(symbol)
    session_day = last_completed_session_date(now)
    if session_day is None or not payload:
        return unavailable_record(symbol, observed_at=observed_at, source=source)
    source = payload.get("source") or source
    bar = select_completed_close(payload.get("bars") or [], session_day)
    currency = payload.get("currency")
    if bar is None or currency is None:
        return unavailable_record(symbol, observed_at=observed_at, source=source)
    return {
        "symbol": symbol,
        "asset_type": ASSET_TYPE,
        "price": bar["close"],
        "currency": currency,
        "price_date": session_day.isoformat(),
        "observed_at": observed_at,
        "source": source,
        "freshness_status": "complete_session",
        "session_status": "regular_close_complete",
    }


def collect_symbol(
    symbol: str,
    *,
    now: datetime | None = None,
    fetch_bars: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    getter = fetch_bars or fetch_daily_bars
    observed_at = now_ny(now).isoformat()
    source = yahoo_source(symbol)
    try:
        payload = getter(symbol)
    except Exception:
        return unavailable_record(symbol, observed_at=observed_at, source=source)
    return quote_from_bars(symbol, payload, now=now)
