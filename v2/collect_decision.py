"""Build one local decision-input snapshot from the latest collector logs.

Read Only on AI-Knowledge. Writes under marume_report logs/ only.
No orders, no verdicts, no Holdings price write-back.
Does not collect live market data.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from v2.collect_report import is_github_actions, write_github_summary
from v2.decision_input import (
    REQUIRED_ASSET_FIELDS,
    build_decision_input,
    decision_exit_code,
    public_decision_summary,
)


def collect_decision_input(
    *,
    now: datetime | None = None,
    log_dir: str | Path = "logs",
    holdings: dict[str, list[dict[str, str]]] | None = None,
    holdings_error: str | None = None,
    write_markdown: bool = True,
) -> dict[str, Any]:
    return build_decision_input(
        now=now,
        log_dir=log_dir,
        holdings=holdings,
        holdings_error=holdings_error,
        write_markdown=write_markdown,
    )


def finish_decision(document: dict[str, Any]) -> int:
    for row in document.get("assets") or []:
        missing = [name for name in REQUIRED_ASSET_FIELDS if name not in row]
        if missing:
            print(json.dumps({"market": "decision_input", "error": "missing_fields"}, ensure_ascii=False))
            return 1
    payload = public_decision_summary(document)
    print(json.dumps(payload, ensure_ascii=False))
    if is_github_actions():
        write_github_summary(payload)
    return decision_exit_code(document)


def main() -> int:
    document = collect_decision_input(log_dir="logs")
    return finish_decision(document)


if __name__ == "__main__":
    sys.exit(main())
