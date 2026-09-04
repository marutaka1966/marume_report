"""Collect official issuer NAVs for Holdings investment trusts.

Read Only on AI-Knowledge. Writes JSON under marume_report logs/ only.
No orders, no verdicts, no Holdings price write-back.
Does not collect JP or US equities.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from v2.collect_report import finish_collection, print_local_log_line
from v2.fund_nav import REQUIRED_FIELDS, collect_fund
from v2.holdings import HOLDINGS_FILE, load_fund_names
from v2.jp_session import now_tokyo
from v2.logstore import _reject_canonical_write

LOG_KIND = "fund_official_navs"


def collect_fund_navs(
    *,
    now: datetime | None = None,
    log_dir: str | Path | bool | None = "logs",
    names: list[str] | None = None,
    fetch_page: Callable[[str], str | None] | None = None,
    fetch_details: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    observed_at = now_tokyo(now).isoformat()
    holdings_error = None
    if names is None:
        names, holdings_error = load_fund_names()
    quotes: list[dict[str, Any]] = []
    for name in names:
        quotes.append(
            collect_fund(
                name,
                now=now,
                fetch_page=fetch_page,
                fetch_details=fetch_details,
            )
        )
    document = {
        "log_kind": LOG_KIND,
        "observed_at": observed_at,
        "holdings_file": HOLDINGS_FILE,
        "holdings_error": holdings_error,
        "quotes": quotes,
    }
    if log_dir:
        path = write_fund_navs(document, log_dir=log_dir)
        document["log_path"] = str(path)
        print_local_log_line("FUND_NAV_LOG", path)
    return document


def write_fund_navs(document: dict[str, Any], *, log_dir: str | Path = "logs") -> Path:
    root = Path(log_dir).expanduser().resolve()
    _reject_canonical_write(root)
    day = datetime.now(timezone.utc).date().isoformat()
    dest_dir = root / day
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%H%M%SZ")
    path = dest_dir / f"fund-nav-{stamp}.json"
    _reject_canonical_write(path)
    payload = {key: value for key, value in document.items() if key != "log_path"}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    document = collect_fund_navs(log_dir="logs")
    return finish_collection("funds", document, required_fields=REQUIRED_FIELDS)


if __name__ == "__main__":
    sys.exit(main())
