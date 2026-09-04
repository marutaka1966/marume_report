"""Collect completed US regular closes for Holdings tickers.

Read Only on AI-Knowledge. Writes JSON under marume_report logs/ only.
No orders, no verdicts, no Holdings price write-back.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from v2.collect_report import finish_collection, print_local_log_line
from v2.holdings import HOLDINGS_FILE, load_us_tickers
from v2.logstore import _reject_canonical_write
from v2.session_logs import find_complete_session_log
from v2.us_closes import REQUIRED_FIELDS, collect_symbol
from v2.us_session import last_completed_session_date, now_ny, session_phase

LOG_KIND = "us_regular_closes"


def collect_us_regular_closes(
    *,
    now: datetime | None = None,
    log_dir: str | Path | bool | None = "logs",
    tickers: list[str] | None = None,
    fetch_bars: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    observed_at = now_ny(now).isoformat()
    if isinstance(log_dir, (str, Path)):
        reused = _reuse_complete_log(log_dir, now=now)
        if reused is not None:
            return reused
    holdings_error = None
    if tickers is None:
        tickers, holdings_error = load_us_tickers()
    quotes: list[dict[str, Any]] = []
    for symbol in tickers:
        quotes.append(collect_symbol(symbol, now=now, fetch_bars=fetch_bars))
    document = {
        "log_kind": LOG_KIND,
        "observed_at": observed_at,
        "observation_session": session_phase(now),
        "holdings_file": HOLDINGS_FILE,
        "holdings_error": holdings_error,
        "quotes": quotes,
    }
    if log_dir:
        path = write_us_closes(document, log_dir=log_dir)
        document["log_path"] = str(path)
        print_local_log_line("US_CLOSES_LOG", path)
    return document


def _reuse_complete_log(log_dir: str | Path, *, now: datetime | None) -> dict[str, Any] | None:
    session = last_completed_session_date(now)
    if session is None:
        return None
    found = find_complete_session_log(
        log_dir,
        log_kind=LOG_KIND,
        filename_prefix="us-closes",
        price_date=session.isoformat(),
    )
    if found is None:
        return None
    document = dict(found[0])
    path = found[1]
    document["log_path"] = str(path)
    document["reused_log"] = True
    print_local_log_line("US_CLOSES_LOG", path)
    return document


def write_us_closes(document: dict[str, Any], *, log_dir: str | Path = "logs") -> Path:
    root = Path(log_dir).expanduser().resolve()
    _reject_canonical_write(root)
    day = datetime.now(timezone.utc).date().isoformat()
    dest_dir = root / day
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%H%M%SZ")
    path = dest_dir / f"us-closes-{stamp}.json"
    _reject_canonical_write(path)
    payload = {key: value for key, value in document.items() if key not in {"log_path", "reused_log"}}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    document = collect_us_regular_closes(log_dir="logs")
    return finish_collection("us", document, required_fields=REQUIRED_FIELDS)


if __name__ == "__main__":
    sys.exit(main())
