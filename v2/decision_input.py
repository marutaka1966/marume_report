"""Build daily decision-input JSON from Holdings and local collector logs.

Read Only on AI-Knowledge. No orders. No FX conversion. No price write-back.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2 import DATA_UNAVAILABLE
from v2.collect_jp import LOG_KIND as JP_LOG_KIND
from v2.collect_funds import LOG_KIND as FUND_LOG_KIND
from v2.collect_report import print_local_log_line, quote_ok
from v2.collect_us import LOG_KIND as US_LOG_KIND
from v2.holdings import HOLDINGS_FILE, load_holding_rows
from v2.jp_session import last_completed_session_date as jp_session_date
from v2.logstore import FORBIDDEN_PATH_PARTS, _reject_canonical_write
from v2.session_logs import latest_log
from v2.us_session import last_completed_session_date as us_session_date

LOG_KIND = "decision_input"
STATUS_OK = "ok"
STATUS_READY = "READY"
STATUS_REVIEW = "NEEDS_REVIEW"
MISSING_LOG = "MISSING_LOG"
MISSING_QUOTE = "MISSING_QUOTE"
STALE_SESSION = "STALE_SESSION"
INCOMPLETE_SESSION = "INCOMPLETE_SESSION"
FRESHNESS_UNKNOWN = "FRESHNESS_UNKNOWN"
UNKNOWN_QUOTE_ERROR = "UNKNOWN_QUOTE_ERROR"
HOLDINGS_UNREAD = "HOLDINGS_UNREAD"

EQUITY_FRESHNESS = "complete_session"
EQUITY_SESSION_STATUS = "regular_close_complete"
EQUITY_FRESHNESS_BASIS = "target_completed_session"
FUND_FRESHNESS = "latest_official_published"
FUND_FRESHNESS_BASIS = "official_current_value"

PUBLIC_QUOTE_REASONS = frozenset(
    {
        DATA_UNAVAILABLE,
        "HTTP_401",
        "HTTP_403",
        "HTTP_429",
        "TIMEOUT",
        "DNS_ERROR",
        "CONNECTION_ERROR",
        "JSON_PARSE_ERROR",
        "MISSING_REGULAR_CLOSE",
        "SESSION_NOT_COMPLETE",
        "UNKNOWN_FETCH_ERROR",
        "BLOCKED_BY_SOURCE",
        "HTML_PARSE_ERROR",
        "AMBIGUOUS_DATE",
        "MISSING_NAV",
        "MISSING_DATE",
        "UNMAPPED_NAME",
    }
)

REQUIRED_ASSET_FIELDS = (
    "asset_class",
    "symbol",
    "name",
    "quantity",
    "avg_cost",
    "cost_amount",
    "price",
    "currency",
    "price_date",
    "observed_at",
    "source",
    "freshness_status",
    "freshness_basis",
    "collection_status",
    "usability_status",
)

CLASS_JP = "jp_equity"
CLASS_US = "us_equity"
CLASS_FUND = "investment_trust"


def build_decision_input(
    *,
    now: datetime | None = None,
    log_dir: str | Path = "logs",
    holdings: dict[str, list[dict[str, str]]] | None = None,
    holdings_error: str | None = None,
    write_markdown: bool = True,
) -> dict[str, Any]:
    observed_at = datetime.now(timezone.utc).isoformat()
    if holdings is None:
        holdings, holdings_error = load_holding_rows()
    jp_date = _iso_or_unavailable(jp_session_date(now))
    us_date = _iso_or_unavailable(us_session_date(now))
    jp_log, jp_path = _load_log(log_dir, JP_LOG_KIND, "jp-closes")
    us_log, us_path = _load_log(log_dir, US_LOG_KIND, "us-closes")
    fund_log, fund_path = _load_log(log_dir, FUND_LOG_KIND, "fund-nav")

    jp_assets = _merge_equities(
        holdings.get("jp") or [],
        quotes=_quote_map(jp_log, key="symbol"),
        asset_class=CLASS_JP,
        session_date=jp_date,
        log_present=jp_log is not None,
    )
    us_assets = _merge_equities(
        holdings.get("us") or [],
        quotes=_quote_map(us_log, key="symbol"),
        asset_class=CLASS_US,
        session_date=us_date,
        log_present=us_log is not None,
    )
    fund_assets = _merge_funds(
        holdings.get("funds") or [],
        quotes=_quote_map(fund_log, key="name"),
        log_present=fund_log is not None,
    )
    assets = jp_assets + us_assets + fund_assets
    fund_dates = {
        row["price_date"]
        for row in fund_assets
        if row["usability_status"] == STATUS_OK and row["price_date"] != DATA_UNAVAILABLE
    }
    fund_date = next(iter(fund_dates)) if len(fund_dates) == 1 else DATA_UNAVAILABLE
    summary = _summary(
        jp_assets,
        us_assets,
        fund_assets,
        holdings_error,
        jp_session_date=jp_date,
        us_session_date=us_date,
    )
    document = {
        "log_kind": LOG_KIND,
        "observed_at": observed_at,
        "holdings_file": HOLDINGS_FILE,
        "holdings_error": holdings_error,
        "source_logs": {
            "jp": str(jp_path) if jp_path else DATA_UNAVAILABLE,
            "us": str(us_path) if us_path else DATA_UNAVAILABLE,
            "funds": str(fund_path) if fund_path else DATA_UNAVAILABLE,
        },
        "session_dates": {"jp": jp_date, "us": us_date, "funds": fund_date},
        "summary": summary,
        "assets": assets,
    }
    if log_dir:
        path = write_decision_input(document, log_dir=log_dir, write_markdown=write_markdown)
        document["log_path"] = str(path)
        print_local_log_line("DECISION_INPUT_LOG", path)
    return document


def write_decision_input(
    document: dict[str, Any],
    *,
    log_dir: str | Path = "logs",
    write_markdown: bool = True,
) -> Path:
    root = Path(log_dir).expanduser().resolve()
    _reject_canonical_write(root)
    day = datetime.now(timezone.utc).date().isoformat()
    dest_dir = root / day
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%H%M%SZ")
    path = dest_dir / f"decision-input-{stamp}.json"
    _reject_canonical_write(path)
    payload = {key: value for key, value in document.items() if key != "log_path"}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if write_markdown:
        md_path = path.with_suffix(".md")
        if any(part in md_path.parts for part in FORBIDDEN_PATH_PARTS):
            raise ValueError("log path must not target AI-Knowledge")
        md_path.write_text(_markdown(payload), encoding="utf-8")
    return path


def public_decision_summary(document: dict[str, Any]) -> dict[str, Any]:
    summary = document.get("summary") or {}
    reasons = Counter()
    for row in document.get("assets") or []:
        if not isinstance(row, dict):
            continue
        status = row.get("usability_status")
        if status != STATUS_OK:
            reasons[status if isinstance(status, str) and status else DATA_UNAVAILABLE] += 1
    if document.get("holdings_error"):
        reasons[HOLDINGS_UNREAD] += 1
    return {
        "market": "decision_input",
        "price_fetch_succeeded": int(summary.get("price_fetch_succeeded") or 0),
        "price_fetch_failed": int(summary.get("price_fetch_failed") or 0),
        "decision_usable": int(summary.get("decision_usable") or 0),
        "decision_unusable": int(summary.get("decision_unusable") or 0),
        "jp_ok": int(summary.get("jp_ok") or 0),
        "jp_failed": int(summary.get("jp_failed") or 0),
        "us_ok": int(summary.get("us_ok") or 0),
        "us_failed": int(summary.get("us_failed") or 0),
        "funds_ok": int(summary.get("funds_ok") or 0),
        "funds_failed": int(summary.get("funds_failed") or 0),
        "missing": int(summary.get("missing") or 0),
        "decision_status": summary.get("decision_status") or STATUS_REVIEW,
        "reasons": [{"reason": reason, "count": count} for reason, count in sorted(reasons.items())],
    }


def decision_exit_code(document: dict[str, Any]) -> int:
    if document.get("holdings_error"):
        return 1
    assets = list(document.get("assets") or [])
    if not assets:
        return 1
    if sum(1 for row in assets if row.get("collection_status") == STATUS_OK) == 0:
        return 1
    return 0


def _load_log(log_dir: str | Path, log_kind: str, prefix: str) -> tuple[dict[str, Any] | None, Path | None]:
    found = latest_log(log_dir, log_kind=log_kind, filename_prefix=prefix)
    if found is None:
        return None, None
    return found


def _quote_map(document: dict[str, Any] | None, *, key: str) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    if not document:
        return mapping
    for row in document.get("quotes") or []:
        if not isinstance(row, dict):
            continue
        ident = row.get(key)
        if isinstance(ident, str) and ident and ident != DATA_UNAVAILABLE:
            mapping[ident] = row
    return mapping


def _merge_equities(
    holdings: list[dict[str, str]],
    *,
    quotes: dict[str, dict[str, Any]],
    asset_class: str,
    session_date: str,
    log_present: bool,
) -> list[dict[str, Any]]:
    assets = []
    for holding in holdings:
        symbol = holding["symbol"]
        quote = quotes.get(symbol)
        assets.append(
            _asset_from_quote(
                holding,
                quote,
                asset_class=asset_class,
                session_date=session_date,
                log_present=log_present,
                price_field="price",
            )
        )
    return assets


def _merge_funds(
    holdings: list[dict[str, str]],
    *,
    quotes: dict[str, dict[str, Any]],
    log_present: bool,
) -> list[dict[str, Any]]:
    assets = []
    for holding in holdings:
        quote = quotes.get(holding["name"])
        assets.append(
            _asset_from_quote(
                holding,
                quote,
                asset_class=CLASS_FUND,
                session_date=DATA_UNAVAILABLE,
                log_present=log_present,
                price_field="nav",
            )
        )
    return assets


def _asset_from_quote(
    holding: dict[str, str],
    quote: dict[str, Any] | None,
    *,
    asset_class: str,
    session_date: str,
    log_present: bool,
    price_field: str,
) -> dict[str, Any]:
    row = {
        "asset_class": asset_class,
        "symbol": holding.get("symbol") or DATA_UNAVAILABLE,
        "name": holding.get("name") or DATA_UNAVAILABLE,
        "quantity": holding.get("quantity") or DATA_UNAVAILABLE,
        "avg_cost": holding.get("avg_cost") or DATA_UNAVAILABLE,
        "cost_amount": holding.get("cost_amount") or DATA_UNAVAILABLE,
        "price": DATA_UNAVAILABLE,
        "currency": DATA_UNAVAILABLE,
        "price_date": DATA_UNAVAILABLE,
        "observed_at": DATA_UNAVAILABLE,
        "source": DATA_UNAVAILABLE,
        "freshness_status": DATA_UNAVAILABLE,
        "freshness_basis": DATA_UNAVAILABLE,
        "collection_status": MISSING_QUOTE if log_present else MISSING_LOG,
        "usability_status": MISSING_QUOTE if log_present else MISSING_LOG,
    }
    if quote is None:
        return row
    if not quote_ok(quote):
        row["collection_status"] = _quote_status(quote)
        row["usability_status"] = row["collection_status"]
        row["observed_at"] = _present(quote.get("observed_at"))
        row["source"] = _present(quote.get("source"))
        return row
    price_date = quote.get("price_date")
    freshness = _present(quote.get("freshness_status"))
    freshness_basis = _present(quote.get("freshness_basis"))
    price = quote.get(price_field, DATA_UNAVAILABLE)
    row.update(
        {
            "price_date": _present(price_date),
            "observed_at": _present(quote.get("observed_at")),
            "source": _present(quote.get("source")),
            "freshness_status": freshness,
            "freshness_basis": freshness_basis,
            "collection_status": STATUS_OK,
            "usability_status": STATUS_OK,
        }
    )
    currency = _present(quote.get("currency"))
    if price in (None, "", DATA_UNAVAILABLE) or currency == DATA_UNAVAILABLE or row["price_date"] == DATA_UNAVAILABLE:
        row["collection_status"] = DATA_UNAVAILABLE
        row["usability_status"] = DATA_UNAVAILABLE
        return row
    if asset_class in {CLASS_JP, CLASS_US}:
        if session_date == DATA_UNAVAILABLE or price_date != session_date:
            row["usability_status"] = STALE_SESSION
        elif freshness != EQUITY_FRESHNESS:
            row["usability_status"] = FRESHNESS_UNKNOWN
        elif quote.get("session_status") != EQUITY_SESSION_STATUS:
            row["usability_status"] = INCOMPLETE_SESSION
        else:
            row["freshness_basis"] = EQUITY_FRESHNESS_BASIS
    elif asset_class == CLASS_FUND:
        if freshness != FUND_FRESHNESS or freshness_basis != FUND_FRESHNESS_BASIS:
            row["usability_status"] = FRESHNESS_UNKNOWN
    if row["usability_status"] == STATUS_OK:
        row["price"] = price
        row["currency"] = currency
    return row


def _summary(
    jp_assets: list[dict[str, Any]],
    us_assets: list[dict[str, Any]],
    fund_assets: list[dict[str, Any]],
    holdings_error: str | None,
    *,
    jp_session_date: str,
    us_session_date: str,
) -> dict[str, Any]:
    def counts(rows: list[dict[str, Any]]) -> tuple[int, int]:
        fetched = sum(1 for row in rows if row["collection_status"] == STATUS_OK)
        usable = sum(1 for row in rows if row["usability_status"] == STATUS_OK)
        return fetched, usable

    jp_fetched, jp_ok = counts(jp_assets)
    us_fetched, us_ok = counts(us_assets)
    funds_fetched, funds_ok = counts(fund_assets)
    all_assets = (*jp_assets, *us_assets, *fund_assets)
    fetched = jp_fetched + us_fetched + funds_fetched
    usable = jp_ok + us_ok + funds_ok
    missing = sum(
        1
        for row in all_assets
        if row["collection_status"] in {MISSING_LOG, MISSING_QUOTE}
    )
    ready = (
        not holdings_error
        and jp_assets
        and us_assets
        and fund_assets
        and all(_ready_asset(row, expected_session_date=jp_session_date) for row in jp_assets)
        and all(_ready_asset(row, expected_session_date=us_session_date) for row in us_assets)
        and all(_ready_asset(row) for row in fund_assets)
    )
    return {
        "price_fetch_succeeded": fetched,
        "price_fetch_failed": len(all_assets) - fetched,
        "decision_usable": usable,
        "decision_unusable": len(all_assets) - usable,
        "jp_fetched": jp_fetched,
        "jp_fetch_failed": len(jp_assets) - jp_fetched,
        "jp_ok": jp_ok,
        "jp_failed": len(jp_assets) - jp_ok,
        "us_fetched": us_fetched,
        "us_fetch_failed": len(us_assets) - us_fetched,
        "us_ok": us_ok,
        "us_failed": len(us_assets) - us_ok,
        "funds_fetched": funds_fetched,
        "funds_fetch_failed": len(fund_assets) - funds_fetched,
        "funds_ok": funds_ok,
        "funds_failed": len(fund_assets) - funds_ok,
        "missing": missing,
        "decision_status": STATUS_READY if ready else STATUS_REVIEW,
    }


def _ready_asset(row: dict[str, Any], *, expected_session_date: str | None = None) -> bool:
    if row["collection_status"] != STATUS_OK or row["usability_status"] != STATUS_OK:
        return False
    required = ("price", "currency", "price_date", "observed_at", "source", "freshness_status", "freshness_basis")
    if not all(row.get(name) not in (None, "", DATA_UNAVAILABLE) for name in required):
        return False
    if row.get("asset_class") in {CLASS_JP, CLASS_US}:
        return (
            expected_session_date not in (None, "", DATA_UNAVAILABLE)
            and row.get("price_date") == expected_session_date
            and row.get("freshness_status") == EQUITY_FRESHNESS
            and row.get("freshness_basis") == EQUITY_FRESHNESS_BASIS
        )
    if row.get("asset_class") == CLASS_FUND:
        return (
            row.get("freshness_status") == FUND_FRESHNESS
            and row.get("freshness_basis") == FUND_FRESHNESS_BASIS
        )
    return False


def _quote_status(quote: dict[str, Any]) -> str:
    error = quote.get("error")
    if isinstance(error, str) and error.strip() in PUBLIC_QUOTE_REASONS and error.strip() != DATA_UNAVAILABLE:
        return error.strip()
    return UNKNOWN_QUOTE_ERROR


def _present(value: object) -> str:
    if isinstance(value, str) and value.strip() and value != DATA_UNAVAILABLE:
        return value
    return DATA_UNAVAILABLE


def _iso_or_unavailable(day: object) -> str:
    if day is None:
        return DATA_UNAVAILABLE
    iso = getattr(day, "isoformat", None)
    if callable(iso):
        return iso()
    return DATA_UNAVAILABLE


def _markdown(document: dict[str, Any]) -> str:
    summary = document.get("summary") or {}
    dates = document.get("session_dates") or {}
    lines = [
        "# Decision input",
        "",
        f"- decision_status: {summary.get('decision_status')}",
        f"- price_fetch: {summary.get('price_fetch_succeeded')}/{summary.get('price_fetch_failed')}",
        f"- decision_usable: {summary.get('decision_usable')}/{summary.get('decision_unusable')}",
        f"- jp: {summary.get('jp_ok')}/{summary.get('jp_failed')}",
        f"- us: {summary.get('us_ok')}/{summary.get('us_failed')}",
        f"- funds: {summary.get('funds_ok')}/{summary.get('funds_failed')}",
        f"- missing: {summary.get('missing')}",
        f"- session_dates: jp={dates.get('jp')} us={dates.get('us')} funds={dates.get('funds')}",
        "",
        "| class | id | qty | price | ccy | price_date | collection | usability |",
        "|-------|----|-----|-------|-----|------------|------------|-----------|",
    ]
    for row in document.get("assets") or []:
        ident = row.get("symbol") if row.get("symbol") != DATA_UNAVAILABLE else row.get("name")
        lines.append(
            "| {cls} | {ident} | {qty} | {price} | {ccy} | {day} | {collection} | {usability} |".format(
                cls=row.get("asset_class"),
                ident=ident,
                qty=row.get("quantity"),
                price=row.get("price"),
                ccy=row.get("currency"),
                day=row.get("price_date"),
                collection=row.get("collection_status"),
                usability=row.get("usability_status"),
            )
        )
    return "\n".join(lines) + "\n"
