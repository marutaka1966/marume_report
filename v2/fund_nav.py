"""Official issuer NAV and price_date. Missing or ambiguous values stay unavailable."""

from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from typing import Any, Callable
from urllib.parse import urlparse

from v2 import DATA_UNAVAILABLE
from v2.fund_fetch import (
    AMBIGUOUS_DATE,
    BLOCKED_BY_SOURCE,
    HTML_PARSE_ERROR,
    JSON_PARSE_ERROR,
    MISSING_DATE,
    MISSING_NAV,
    UNMAPPED_NAME,
    UNKNOWN_FETCH_ERROR,
    _close_http_error,
    fetch_official_json,
    fetch_official_text,
    public_fund_cause,
    to_public_fetch_cause,
)
from v2.fund_sources import MUFG_FUND_DETAILS, OFFICIAL_FUND_PAGES, PARSER_DAIWA, PARSER_MUFG, PARSER_PICTET, PARSER_SBI
from v2.jp_session import now_tokyo
from v2.us_closes import CONNECTION_ERROR, DNS_ERROR, TIMEOUT, classify_fetch_error

ASSET_TYPE = "investment_trust"
STATUS_OK = "ok"

# Public cause aliases used by tests and records.
ERR_UNMAPPED = UNMAPPED_NAME
ERR_FETCH = UNKNOWN_FETCH_ERROR
ERR_API_FETCH = UNKNOWN_FETCH_ERROR
ERR_MISSING_NAV = MISSING_NAV
ERR_MISSING_DATE = MISSING_DATE
ERR_AMBIGUOUS_DATE = AMBIGUOUS_DATE
ERR_HTML = HTML_PARSE_ERROR
ERR_JSON = JSON_PARSE_ERROR
ERR_BLOCKED = BLOCKED_BY_SOURCE

REQUIRED_FIELDS = (
    "name",
    "nav",
    "currency",
    "price_date",
    "observed_at",
    "source",
    "status",
    "error",
)

_FUND_CD_INPUT = re.compile(
    r'<input[^>]*id=["\']js-fund-code["\'][^>]*value=["\'](\d+)["\']',
    re.IGNORECASE,
)
_FUND_CD_INPUT_ALT = re.compile(
    r'<input[^>]*value=["\'](\d+)["\'][^>]*id=["\']js-fund-code["\']',
    re.IGNORECASE,
)
_MUFG_URL_CD = re.compile(r"/fund/(\d+)\.html(?:$|\?)")
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_JP_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_SLASH_DATE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
_YMD8 = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_TABLE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
_ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL = re.compile(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", re.IGNORECASE | re.DOTALL)
_FPRICE = re.compile(r'class=["\']fprice["\'][^>]*>\s*([0-9,]+)', re.IGNORECASE)
_NAV_YEN = re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)\s*円")
_HYOKA_DATE = re.compile(
    r"評価基準日[:：]?\s*(?:\d{4}年\d{1,2}月\d{1,2}日|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{8})"
)


def official_page(name: str) -> dict[str, str] | None:
    return OFFICIAL_FUND_PAGES.get(name)


def mufg_details_url(fund_cd: str) -> str:
    return MUFG_FUND_DETAILS.format(fund_cd=fund_cd)


def fetch_text(url: str) -> str | None:
    text, _error = fetch_official_text(url)
    return text


def fetch_json(url: str) -> dict[str, Any] | None:
    payload, _error = fetch_official_json(url)
    return payload


def unavailable_record(
    name: str,
    *,
    observed_at: str,
    source: str,
    error: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "asset_type": ASSET_TYPE,
        "nav": DATA_UNAVAILABLE,
        "currency": DATA_UNAVAILABLE,
        "price_date": DATA_UNAVAILABLE,
        "observed_at": observed_at,
        "source": source,
        "status": DATA_UNAVAILABLE,
        "error": public_fund_cause(error),
    }


def ok_record(
    name: str,
    *,
    nav: float,
    currency: str,
    price_date: str,
    observed_at: str,
    source: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "asset_type": ASSET_TYPE,
        "nav": nav,
        "currency": currency,
        "price_date": price_date,
        "observed_at": observed_at,
        "source": source,
        "status": STATUS_OK,
        "error": None,
    }


def parse_labeled_date(text: str) -> str | None:
    """Parse one date from a single labeled field. Do not pick among many dates."""
    text = text.strip()
    iso = _ISO_DATE.search(text)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    jp = _JP_DATE.search(text)
    if jp:
        return f"{int(jp.group(1)):04d}-{int(jp.group(2)):02d}-{int(jp.group(3)):02d}"
    slash = _SLASH_DATE.search(text)
    if slash:
        return f"{int(slash.group(1)):04d}-{int(slash.group(2)):02d}-{int(slash.group(3)):02d}"
    compact = _YMD8.fullmatch(re.sub(r"[.\s]", "", text))
    if compact:
        return f"{compact.group(1)}-{compact.group(2)}-{compact.group(3)}"
    return None


def _mufg_fund_cd_from_url(url: str) -> str | None:
    match = _MUFG_URL_CD.search(urlparse(url).path)
    return match.group(1) if match else None


def _mufg_fund_cd_from_html(html: str) -> str | None:
    match = _FUND_CD_INPUT.search(html) or _FUND_CD_INPUT_ALT.search(html)
    return match.group(1) if match else None


def parse_mufg_details(payload: dict[str, Any] | None) -> tuple[float | None, str | None, str | None]:
    """Return (nav, price_date, error). error set when JSON is unusable."""
    if not isinstance(payload, dict):
        return None, None, ERR_JSON
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("status") != 200:
        return None, None, ERR_JSON
    datasets = payload.get("datasets")
    if not isinstance(datasets, dict):
        return None, None, ERR_JSON
    raw_price = datasets.get("cfm_base_price")
    raw_date = datasets.get("cfm_base_date")
    if raw_price in (None, ""):
        return None, None, ERR_MISSING_NAV
    if raw_date in (None, ""):
        return None, None, ERR_MISSING_DATE
    try:
        nav = float(str(raw_price).replace(",", ""))
    except ValueError:
        return None, None, ERR_JSON
    price_date = parse_labeled_date(str(raw_date))
    if price_date is None:
        return None, None, ERR_JSON
    return nav, price_date, None


def parse_pictet_html(html: str) -> tuple[float | None, str | None, str | None]:
    start = html.find("cmp-funds__fund-summary")
    if start < 0:
        return None, None, ERR_HTML
    rest = html[start:]
    end = rest.find("</table>")
    block = rest[: end + 8] if end >= 0 else rest[:4000]
    date_match = re.search(r"基準日[:：]\s*([^<]+)", block)
    if not date_match:
        return None, None, ERR_MISSING_DATE
    price_date = parse_labeled_date(date_match.group(1))
    if price_date is None:
        return None, None, ERR_MISSING_DATE
    nav_match = re.search(
        r"基準価額</td>\s*<td[^>]*>\s*([0-9,]+)\s*円",
        block,
        re.IGNORECASE,
    )
    if not nav_match:
        return None, None, ERR_MISSING_NAV
    try:
        nav = float(nav_match.group(1).replace(",", ""))
    except ValueError:
        return None, None, ERR_HTML
    return nav, price_date, None


def parse_daiwa_html(html: str) -> tuple[float | None, str | None, str | None]:
    start = html.find("p-fundDetail__info")
    if start < 0:
        start = html.find("運用情報")
    if start < 0:
        return None, None, ERR_HTML
    block = html[start : start + 8000]
    date_match = re.search(
        r"基準日[:：]\s*<time[^>]*datetime=[\"']([^\"']*)[\"']",
        block,
        re.IGNORECASE,
    )
    if not date_match or not date_match.group(1).strip():
        return None, None, ERR_MISSING_DATE
    price_date = parse_labeled_date(date_match.group(1))
    if price_date is None:
        return None, None, ERR_MISSING_DATE
    nav_match = re.search(
        r"<th[^>]*>基準価額</th>\s*<td>\s*<p>\s*<span[^>]*>\s*([0-9,]+)\s*</span>\s*円",
        block,
        re.IGNORECASE | re.DOTALL,
    )
    if not nav_match:
        return None, None, ERR_MISSING_NAV
    try:
        nav = float(nav_match.group(1).replace(",", ""))
    except ValueError:
        return None, None, ERR_HTML
    return nav, price_date, None


def _strip_cell(raw: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _all_dates(text: str) -> set[str]:
    dates: set[str] = set()
    for match in _JP_DATE.finditer(text):
        dates.add(f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}")
    for match in _ISO_DATE.finditer(text):
        dates.add(f"{match.group(1)}-{match.group(2)}-{match.group(3)}")
    for match in _SLASH_DATE.finditer(text):
        dates.add(f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}")
    return dates


def _nav_dates(text: str) -> set[str]:
    """Dates tied to 基準価額. Drop 評価基準日 values. Do not guess."""
    return _all_dates(_HYOKA_DATE.sub(" ", text))


def _parse_nav_amount(raw_html: str, text: str) -> float | None:
    match = _FPRICE.search(raw_html) or _NAV_YEN.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_sbi_html(html: str) -> tuple[float | None, str | None, str | None]:
    """Use the 基準価額 column only. Never adopt 評価基準日."""
    for table in _TABLE.findall(html):
        rows = [_CELL.findall(row) for row in _ROW.findall(table)]
        rows = [row for row in rows if row]
        nav_col: int | None = None
        header_at: int | None = None
        for index, row in enumerate(rows):
            for col, cell in enumerate(row):
                if _strip_cell(cell) == "基準価額":
                    nav_col = col
                    header_at = index
                    break
            if nav_col is not None:
                break
        if nav_col is None or header_at is None:
            continue
        column_html = []
        for row in rows[header_at + 1 :]:
            if nav_col < len(row):
                column_html.append(row[nav_col])
        if not column_html:
            continue
        blob_html = " ".join(column_html)
        blob_text = _strip_cell(blob_html)
        dates = _nav_dates(blob_text)
        nav = _parse_nav_amount(blob_html, blob_text)
        if nav is None:
            return None, None, ERR_MISSING_NAV
        if len(dates) > 1:
            return None, None, ERR_AMBIGUOUS_DATE
        if len(dates) == 0:
            return None, None, ERR_MISSING_DATE
        return nav, next(iter(dates)), None

    start = html.find(">基準価額<")
    if start < 0:
        start = html.find("<th>基準価額</th>")
    if start < 0:
        return None, None, ERR_HTML
    block = html[start : start + 2500]
    labeled = re.findall(r"(?<!評価)基準日[:：]\s*([^<]+)", block)
    unique_dates = {parse_labeled_date(item) for item in labeled}
    unique_dates.discard(None)
    if "評価基準日" in block and not unique_dates:
        return None, None, ERR_MISSING_DATE
    if len(unique_dates) > 1:
        return None, None, ERR_AMBIGUOUS_DATE
    if not unique_dates:
        return None, None, ERR_MISSING_DATE
    nav = _parse_nav_amount(block, _strip_cell(block))
    if nav is None:
        return None, None, ERR_MISSING_NAV
    return nav, next(iter(unique_dates)), None


def _page_text(
    url: str,
    fetch_page: Callable[[str], str | None] | None,
) -> tuple[str | None, str | None]:
    if fetch_page is None:
        return fetch_official_text(url)
    try:
        html = fetch_page(url)
    except Exception as exc:
        _close_http_error(exc)
        return None, to_public_fetch_cause(classify_fetch_error(exc))
    if not html:
        return None, UNKNOWN_FETCH_ERROR
    return html, None


def _details_json(
    url: str,
    fetch_details: Callable[[str], dict[str, Any] | None] | None,
    *,
    referer: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if fetch_details is None:
        return fetch_official_json(url, referer=referer)
    try:
        payload = fetch_details(url)
    except Exception as exc:
        _close_http_error(exc)
        return None, to_public_fetch_cause(classify_fetch_error(exc))
    if not payload:
        return None, UNKNOWN_FETCH_ERROR
    if not isinstance(payload, dict):
        return None, JSON_PARSE_ERROR
    return payload, None


def _prefer_fetch_error(*codes: str | None) -> str:
    present = [public_fund_cause(code) for code in codes if code]
    if not present:
        return UNKNOWN_FETCH_ERROR
    if BLOCKED_BY_SOURCE in present:
        return BLOCKED_BY_SOURCE
    for cause in (TIMEOUT, DNS_ERROR, CONNECTION_ERROR):
        if cause in present:
            return cause
    return present[0]


def collect_fund(
    name: str,
    *,
    now: datetime | None = None,
    fetch_page: Callable[[str], str | None] | None = None,
    fetch_details: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    observed_at = now_tokyo(now).isoformat()
    page = official_page(name)
    if page is None:
        return unavailable_record(
            name,
            observed_at=observed_at,
            source=DATA_UNAVAILABLE,
            error=ERR_UNMAPPED,
        )
    source = page["url"]
    parser = page["parser"]
    if parser == PARSER_MUFG:
        return _collect_mufg(
            name,
            page_url=source,
            observed_at=observed_at,
            fetch_page=fetch_page,
            fetch_details=fetch_details,
        )
    html, fetch_error = _page_text(source, fetch_page)
    if not html:
        return unavailable_record(
            name,
            observed_at=observed_at,
            source=source,
            error=fetch_error or ERR_FETCH,
        )
    parsers = {
        PARSER_PICTET: parse_pictet_html,
        PARSER_DAIWA: parse_daiwa_html,
        PARSER_SBI: parse_sbi_html,
    }
    parse = parsers.get(parser)
    if parse is None:
        return unavailable_record(name, observed_at=observed_at, source=source, error=ERR_UNMAPPED)
    nav, price_date, error = parse(html)
    if error or nav is None or price_date is None:
        return unavailable_record(
            name,
            observed_at=observed_at,
            source=source,
            error=error or ERR_HTML,
        )
    return ok_record(
        name,
        nav=nav,
        currency="JPY",
        price_date=price_date,
        observed_at=observed_at,
        source=source,
    )


def _collect_mufg(
    name: str,
    *,
    page_url: str,
    observed_at: str,
    fetch_page: Callable[[str], str | None] | None,
    fetch_details: Callable[[str], dict[str, Any] | None] | None,
) -> dict[str, Any]:
    url_cd = _mufg_fund_cd_from_url(page_url)
    api_error: str | None = None
    if url_cd:
        api_url = mufg_details_url(url_cd)
        record = _mufg_from_api(
            name,
            api_url=api_url,
            observed_at=observed_at,
            fetch_details=fetch_details,
            referer=page_url,
        )
        if record["status"] == STATUS_OK:
            return record
        api_error = record.get("error") if isinstance(record.get("error"), str) else ERR_API_FETCH

    html, html_error = _page_text(page_url, fetch_page)
    if html:
        page_cd = _mufg_fund_cd_from_html(html)
        if url_cd and page_cd and url_cd != page_cd:
            return unavailable_record(name, observed_at=observed_at, source=page_url, error=ERR_HTML)
        fund_cd = page_cd or url_cd
        if fund_cd:
            api_url = mufg_details_url(fund_cd)
            record = _mufg_from_api(
                name,
                api_url=api_url,
                observed_at=observed_at,
                fetch_details=fetch_details,
                referer=page_url,
            )
            if record["status"] == STATUS_OK:
                return record
            api_error = record.get("error") if isinstance(record.get("error"), str) else api_error
        elif not url_cd:
            return unavailable_record(name, observed_at=observed_at, source=page_url, error=ERR_HTML)

    source = mufg_details_url(url_cd) if url_cd else page_url
    return unavailable_record(
        name,
        observed_at=observed_at,
        source=source,
        error=_prefer_fetch_error(html_error if not html else None, api_error, html_error),
    )


def _mufg_from_api(
    name: str,
    *,
    api_url: str,
    observed_at: str,
    fetch_details: Callable[[str], dict[str, Any] | None] | None,
    referer: str,
) -> dict[str, Any]:
    payload, fetch_error = _details_json(api_url, fetch_details, referer=referer)
    if not payload:
        return unavailable_record(
            name,
            observed_at=observed_at,
            source=api_url,
            error=fetch_error or ERR_API_FETCH,
        )
    nav, price_date, error = parse_mufg_details(payload)
    if error or nav is None or price_date is None:
        return unavailable_record(
            name,
            observed_at=observed_at,
            source=api_url,
            error=error or ERR_JSON,
        )
    return ok_record(
        name,
        nav=nav,
        currency="JPY",
        price_date=price_date,
        observed_at=observed_at,
        source=api_url,
    )
