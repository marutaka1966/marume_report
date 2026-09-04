"""Completed US regular-session closes. No live, pre, or post prices."""

from __future__ import annotations

import errno
import json
import socket
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any, Callable

from v2 import DATA_UNAVAILABLE
from v2.us_session import NY, last_completed_session_date, now_ny

HTTP_401 = "HTTP_401"
HTTP_403 = "HTTP_403"
HTTP_429 = "HTTP_429"
TIMEOUT = "TIMEOUT"
DNS_ERROR = "DNS_ERROR"
CONNECTION_ERROR = "CONNECTION_ERROR"
JSON_PARSE_ERROR = "JSON_PARSE_ERROR"
MISSING_REGULAR_CLOSE = "MISSING_REGULAR_CLOSE"
SESSION_NOT_COMPLETE = "SESSION_NOT_COMPLETE"
UNKNOWN_FETCH_ERROR = "UNKNOWN_FETCH_ERROR"

FETCH_CAUSES = frozenset(
    {
        HTTP_401,
        HTTP_403,
        HTTP_429,
        TIMEOUT,
        DNS_ERROR,
        CONNECTION_ERROR,
        JSON_PARSE_ERROR,
        MISSING_REGULAR_CLOSE,
        SESSION_NOT_COMPLETE,
        UNKNOWN_FETCH_ERROR,
    }
)

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


def classify_fetch_error(exc: BaseException) -> str:
    """Map a fetch exception to a public cause code. Do not include URLs or messages."""
    if isinstance(exc, json.JSONDecodeError):
        return JSON_PARSE_ERROR
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:
            return HTTP_401
        if exc.code == 403:
            return HTTP_403
        if exc.code == 429:
            return HTTP_429
        return UNKNOWN_FETCH_ERROR
    if isinstance(exc, TimeoutError) or isinstance(exc, socket.timeout):
        return TIMEOUT
    if isinstance(exc, socket.gaierror):
        return DNS_ERROR
    if isinstance(exc, ConnectionError):
        return CONNECTION_ERROR
    if isinstance(exc, urllib.error.URLError):
        return classify_fetch_error(exc.reason) if isinstance(exc.reason, BaseException) else _classify_reason_text(exc.reason)
    if isinstance(exc, OSError) and exc.errno in {
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.ECONNABORTED,
        errno.EHOSTUNREACH,
        errno.ENETUNREACH,
        errno.ETIMEDOUT,
    }:
        if exc.errno == errno.ETIMEDOUT:
            return TIMEOUT
        return CONNECTION_ERROR
    return UNKNOWN_FETCH_ERROR


def _classify_reason_text(reason: object) -> str:
    text = str(reason).lower()
    if "timed out" in text or "timeout" in text:
        return TIMEOUT
    if "name or service not known" in text or "nodename nor servname" in text or "getaddrinfo" in text:
        return DNS_ERROR
    if "connection" in text or "refused" in text:
        return CONNECTION_ERROR
    return UNKNOWN_FETCH_ERROR


def public_fetch_cause(code: object) -> str:
    if isinstance(code, str) and code in FETCH_CAUSES:
        return code
    return UNKNOWN_FETCH_ERROR


def fetch_daily_bars(symbol: str) -> dict[str, Any] | None:
    """Daily bars only. Ignores regularMarketPrice, preMarketPrice, postMarketPrice."""
    url = yahoo_source(symbol)
    req = urllib.request.Request(url, headers={"User-Agent": "marume-report-v2"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        return {"error": classify_fetch_error(exc)}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": JSON_PARSE_ERROR}
    except (UnicodeDecodeError, ValueError):
        return {"error": UNKNOWN_FETCH_ERROR}
    try:
        result = data["chart"]["result"][0]
        meta = result.get("meta") or {}
        quote = result["indicators"]["quote"][0]
        timestamps = result.get("timestamp") or []
        closes = quote.get("close") or []
    except (KeyError, IndexError, TypeError):
        return {"error": UNKNOWN_FETCH_ERROR}
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
    error: str = UNKNOWN_FETCH_ERROR,
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
        "error": public_fetch_cause(error),
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
    if isinstance(payload, dict) and payload.get("error"):
        return unavailable_record(
            symbol,
            observed_at=observed_at,
            source=source,
            error=public_fetch_cause(payload.get("error")),
        )
    if session_day is None:
        return unavailable_record(
            symbol,
            observed_at=observed_at,
            source=source,
            error=SESSION_NOT_COMPLETE,
        )
    if not payload:
        return unavailable_record(
            symbol,
            observed_at=observed_at,
            source=source,
            error=UNKNOWN_FETCH_ERROR,
        )
    source = payload.get("source") or source
    bar = select_completed_close(payload.get("bars") or [], session_day)
    currency = payload.get("currency")
    if bar is None or currency is None:
        return unavailable_record(
            symbol,
            observed_at=observed_at,
            source=source,
            error=MISSING_REGULAR_CLOSE,
        )
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
    except Exception as exc:
        return unavailable_record(
            symbol,
            observed_at=observed_at,
            source=source,
            error=classify_fetch_error(exc),
        )
    return quote_from_bars(symbol, payload, now=now)
