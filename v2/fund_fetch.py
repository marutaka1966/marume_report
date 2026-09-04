"""Official-page fetch with retries. No unofficial hosts. No secret logging."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from v2.us_closes import (
    CONNECTION_ERROR,
    DNS_ERROR,
    HTTP_401,
    HTTP_403,
    HTTP_429,
    JSON_PARSE_ERROR,
    TIMEOUT,
    UNKNOWN_FETCH_ERROR,
    classify_fetch_error,
)

BLOCKED_BY_SOURCE = "BLOCKED_BY_SOURCE"
HTML_PARSE_ERROR = "HTML_PARSE_ERROR"
AMBIGUOUS_DATE = "AMBIGUOUS_DATE"
MISSING_NAV = "MISSING_NAV"
MISSING_DATE = "MISSING_DATE"
UNMAPPED_NAME = "UNMAPPED_NAME"

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
MAX_ATTEMPTS = 3
TIMEOUT_SEC = 20
BACKOFF_SEC = (0.5, 1.0)
_BLOCK_CODES = frozenset({HTTP_401, HTTP_403, HTTP_429})
_RETRY_CAUSES = frozenset({TIMEOUT, HTTP_429, HTTP_403, CONNECTION_ERROR, DNS_ERROR})

FUND_CAUSES = frozenset(
    {
        HTTP_401,
        HTTP_403,
        HTTP_429,
        TIMEOUT,
        DNS_ERROR,
        CONNECTION_ERROR,
        JSON_PARSE_ERROR,
        HTML_PARSE_ERROR,
        BLOCKED_BY_SOURCE,
        AMBIGUOUS_DATE,
        MISSING_NAV,
        MISSING_DATE,
        UNMAPPED_NAME,
        UNKNOWN_FETCH_ERROR,
    }
)


def public_fund_cause(code: object) -> str:
    if isinstance(code, str) and code in FUND_CAUSES:
        return code
    return UNKNOWN_FETCH_ERROR


def to_public_fetch_cause(cause: str) -> str:
    """Map internal HTTP refusals to BLOCKED_BY_SOURCE. Keep timeout and parse codes."""
    if cause in _BLOCK_CODES:
        return BLOCKED_BY_SOURCE
    return public_fund_cause(cause)


def _headers(accept: str, referer: str | None) -> dict[str, str]:
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": accept,
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _close_http_error(exc: BaseException) -> None:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            exc.close()
        except Exception:
            return


def _retryable(exc: BaseException, cause: str) -> bool:
    if cause == HTTP_401:
        return False
    if cause in _RETRY_CAUSES:
        return True
    return isinstance(exc, urllib.error.HTTPError) and exc.code >= 500


def fetch_official_bytes(
    url: str,
    *,
    accept: str,
    referer: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bytes | None, str | None]:
    """GET an official URL. Returns (body, error). Error is a public cause code."""
    headers = _headers(accept, referer)
    last_error = UNKNOWN_FETCH_ERROR
    for attempt in range(MAX_ATTEMPTS):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                return resp.read(), None
        except Exception as exc:
            last_error = classify_fetch_error(exc)
            _close_http_error(exc)
            if _retryable(exc, last_error) and attempt + 1 < MAX_ATTEMPTS:
                sleep(BACKOFF_SEC[min(attempt, len(BACKOFF_SEC) - 1)])
                continue
            return None, to_public_fetch_cause(last_error)
    return None, to_public_fetch_cause(last_error)


def decode_html_bytes(raw: bytes) -> tuple[str | None, str | None]:
    for encoding in ("utf-8", "cp932", "shift_jis"):
        try:
            return raw.decode(encoding), None
        except UnicodeDecodeError:
            continue
    return None, HTML_PARSE_ERROR


def fetch_official_text(
    url: str,
    *,
    referer: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str | None, str | None]:
    raw, error = fetch_official_bytes(
        url,
        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        referer=referer,
        sleep=sleep,
    )
    if raw is None:
        return None, error
    return decode_html_bytes(raw)


def fetch_official_json(
    url: str,
    *,
    referer: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any] | None, str | None]:
    raw, error = fetch_official_bytes(
        url,
        accept="application/json,text/javascript,*/*;q=0.8",
        referer=referer,
        sleep=sleep,
    )
    if raw is None:
        return None, error
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None, JSON_PARSE_ERROR
    if not isinstance(payload, dict):
        return None, JSON_PARSE_ERROR
    return payload, None
