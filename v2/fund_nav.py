"""Official issuer NAV and price_date. Missing or ambiguous values stay unavailable."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlparse

from v2 import DATA_UNAVAILABLE
from v2.fund_sources import MUFG_FUND_DETAILS, OFFICIAL_FUND_PAGES, PARSER_DAIWA, PARSER_MUFG, PARSER_PICTET, PARSER_SBI
from v2.jp_session import now_tokyo

ASSET_TYPE = "investment_trust"
STATUS_OK = "ok"
USER_AGENT = "marume-report-v2"

ERR_UNMAPPED = "公式ページとの名称対応が不明"
ERR_FETCH = "ページの取得に失敗した"
ERR_API_FETCH = "公式データの取得に失敗した"
ERR_MISSING_NAV = "基準価額が取得できない"
ERR_MISSING_DATE = "基準日が取得できない"
ERR_AMBIGUOUS_DATE = "基準日が一意に確定できない"
ERR_HTML = "HTMLの構造が変わった"
ERR_JSON = "公式データの構造が変わった"

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
_YMD8 = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def official_page(name: str) -> dict[str, str] | None:
    return OFFICIAL_FUND_PAGES.get(name)


def mufg_details_url(fund_cd: str) -> str:
    return MUFG_FUND_DETAILS.format(fund_cd=fund_cd)


def fetch_text(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    for encoding in ("utf-8", "cp932", "shift_jis"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def fetch_json(url: str) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


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
        "error": error,
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
    slash = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", text)
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


def parse_sbi_html(html: str) -> tuple[float | None, str | None, str | None]:
    """SBI AM WealthAdvisor table. Unlabeled NAV dates plus 評価基準日 are not unique."""
    start = html.find(">基準価額<")
    if start < 0:
        start = html.find("<th>基準価額</th>")
    if start < 0:
        return None, None, ERR_HTML
    block = html[start : start + 2500]
    labeled = re.findall(r"(?<!評価)基準日[:：]\s*([^<]+)", block)
    unique_dates = {parse_labeled_date(item) for item in labeled}
    unique_dates.discard(None)
    has_hyoka = "評価基準日" in block
    unlabeled_dates = {parse_labeled_date(item.group(0)) for item in _JP_DATE.finditer(block)}
    unlabeled_dates.discard(None)
    if has_hyoka and not unique_dates:
        return None, None, ERR_AMBIGUOUS_DATE
    if len(unique_dates) > 1:
        return None, None, ERR_AMBIGUOUS_DATE
    if has_hyoka and unique_dates and unlabeled_dates - unique_dates:
        return None, None, ERR_AMBIGUOUS_DATE
    if not unique_dates:
        return None, None, ERR_MISSING_DATE
    nav_match = re.search(r'class="fprice"[^>]*>\s*([0-9,]+)\s*</span>\s*円', block)
    if not nav_match:
        nav_match = re.search(r"([0-9,]+)\s*円", block)
    if not nav_match:
        return None, None, ERR_MISSING_NAV
    try:
        nav = float(nav_match.group(1).replace(",", ""))
    except ValueError:
        return None, None, ERR_HTML
    return nav, next(iter(unique_dates)), None


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
    getter = fetch_page or fetch_text
    details_getter = fetch_details or fetch_json
    try:
        html = getter(source)
    except Exception:
        return unavailable_record(name, observed_at=observed_at, source=source, error=ERR_FETCH)
    if not html:
        return unavailable_record(name, observed_at=observed_at, source=source, error=ERR_FETCH)
    if parser == PARSER_MUFG:
        return _collect_mufg(
            name,
            html=html,
            page_url=source,
            observed_at=observed_at,
            fetch_details=details_getter,
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
    html: str,
    page_url: str,
    observed_at: str,
    fetch_details: Callable[[str], dict[str, Any] | None],
) -> dict[str, Any]:
    page_cd = _mufg_fund_cd_from_html(html)
    url_cd = _mufg_fund_cd_from_url(page_url)
    if not page_cd or not url_cd or page_cd != url_cd:
        return unavailable_record(name, observed_at=observed_at, source=page_url, error=ERR_HTML)
    api_url = mufg_details_url(page_cd)
    try:
        payload = fetch_details(api_url)
    except Exception:
        return unavailable_record(name, observed_at=observed_at, source=api_url, error=ERR_API_FETCH)
    if not payload:
        return unavailable_record(name, observed_at=observed_at, source=api_url, error=ERR_API_FETCH)
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
