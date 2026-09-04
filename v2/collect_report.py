"""Public collection summary. No tickers, names, prices, or quote JSON."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from v2 import DATA_UNAVAILABLE

REASON_HOLDINGS = "holdings_unreadable"
REASON_NO_QUOTES = "no_quotes"
REASON_MISSING_FIELDS = "missing_fields"


def is_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def print_local_log_line(prefix: str, path: Path | str) -> None:
    if is_github_actions():
        return
    print(f"{prefix} {path}")


def quote_ok(row: dict[str, Any]) -> bool:
    if "status" in row:
        return row.get("status") != DATA_UNAVAILABLE
    return row.get("price") != DATA_UNAVAILABLE


def quote_reason(row: dict[str, Any]) -> str:
    error = row.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    return DATA_UNAVAILABLE


def public_summary(market: str, document: dict[str, Any]) -> dict[str, Any]:
    quotes = list(document.get("quotes") or [])
    ok = sum(1 for row in quotes if quote_ok(row))
    failed_rows = [row for row in quotes if not quote_ok(row)]
    reason_counts = Counter(quote_reason(row) for row in failed_rows)
    reasons = [{"reason": reason, "count": count} for reason, count in sorted(reason_counts.items())]
    if not quotes and not document.get("holdings_error"):
        reasons = [{"reason": REASON_NO_QUOTES, "count": 1}]
    payload: dict[str, Any] = {
        "market": market,
        "ok": ok,
        "failed": len(failed_rows),
        "reasons": reasons,
    }
    if document.get("holdings_error"):
        payload["holdings"] = REASON_HOLDINGS
    return payload


def collection_exit_code(document: dict[str, Any]) -> int:
    quotes = list(document.get("quotes") or [])
    if document.get("holdings_error"):
        return 1
    if not quotes:
        return 1
    if sum(1 for row in quotes if quote_ok(row)) == 0:
        return 1
    return 0


def write_github_summary(payload: dict[str, Any]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not path:
        return
    lines = [
        f"## {payload['market']}",
        f"- ok: {payload['ok']}",
        f"- failed: {payload['failed']}",
    ]
    if payload.get("holdings") == REASON_HOLDINGS:
        lines.append(f"- holdings: {REASON_HOLDINGS}")
    if payload.get("reasons"):
        lines.append("- reasons:")
        for item in payload["reasons"]:
            lines.append(f"  - {item['reason']} ({item['count']})")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def finish_collection(
    market: str,
    document: dict[str, Any],
    *,
    required_fields: tuple[str, ...],
) -> int:
    """Print a public summary. Exit 1 only when holdings are unread or every quote failed."""
    quotes = list(document.get("quotes") or [])
    for row in quotes:
        missing = [name for name in required_fields if name not in row]
        if missing:
            print(json.dumps({"market": market, "error": REASON_MISSING_FIELDS}, ensure_ascii=False))
            return 1
    payload = public_summary(market, document)
    print(json.dumps(payload, ensure_ascii=False))
    write_github_summary(payload)
    return collection_exit_code(document)
