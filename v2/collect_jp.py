"""Collect completed TSE regular closes for Holdings JP tickers.

Read Only on AI-Knowledge. Writes JSON under marume_report logs/ only.
No orders, no verdicts, no Holdings price write-back.
Does not collect US stocks or funds.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from v2 import DATA_UNAVAILABLE
from v2.holdings import HOLDINGS_FILE, load_jp_tickers
from v2.jp_closes import REQUIRED_FIELDS, collect_symbol
from v2.jp_session import now_tokyo, session_phase
from v2.logstore import _reject_canonical_write

LOG_KIND = "jp_regular_closes"


def collect_jp_regular_closes(
    *,
    now: datetime | None = None,
    log_dir: str | Path | bool | None = "logs",
    tickers: list[str] | None = None,
    fetch_bars: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    observed_at = now_tokyo(now).isoformat()
    holdings_error = None
    if tickers is None:
        tickers, holdings_error = load_jp_tickers()
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
        path = write_jp_closes(document, log_dir=log_dir)
        document["log_path"] = str(path)
        print(f"JP_CLOSES_LOG {path}")
    return document


def write_jp_closes(document: dict[str, Any], *, log_dir: str | Path = "logs") -> Path:
    root = Path(log_dir).expanduser().resolve()
    _reject_canonical_write(root)
    day = datetime.now(timezone.utc).date().isoformat()
    dest_dir = root / day
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%H%M%SZ")
    path = dest_dir / f"jp-closes-{stamp}.json"
    _reject_canonical_write(path)
    payload = {key: value for key, value in document.items() if key != "log_path"}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    document = collect_jp_regular_closes(log_dir="logs")
    ok = sum(1 for row in document["quotes"] if row.get("price") != DATA_UNAVAILABLE)
    failed = [row["symbol"] for row in document["quotes"] if row.get("price") == DATA_UNAVAILABLE]
    print(json.dumps({"ok": ok, "failed": failed}, ensure_ascii=False))
    for row in document["quotes"]:
        missing = [name for name in REQUIRED_FIELDS if name not in row]
        if missing:
            print(f"MISSING_FIELDS {row.get('symbol')} {missing}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
