"""Persist decision logs as JSON. Never write to AI-Knowledge or git-tracked paths."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

FORBIDDEN_PATH_PARTS = ("AI-Knowledge",)


def write_run(
    payloads: list[dict[str, Any]],
    *,
    log_dir: str | Path = "logs",
    market: dict[str, Any] | None = None,
) -> Path:
    """Write one run JSON under logs/YYYY-MM-DD/.

    Fields: date, Decision reason, inputs_used, indicators, missing.
    """
    root = Path(log_dir).expanduser().resolve()
    _reject_knowledge_path(root)
    date = datetime.now(timezone.utc).date().isoformat()
    dest_dir = root / date
    _reject_knowledge_path(dest_dir.resolve())
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%H%M%SZ")
    path = dest_dir / f"run-{stamp}.json"
    document = {
        "date": date,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "decisions": [_row(payload, market) for payload in payloads],
    }
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _row(payload: dict[str, Any], market: dict[str, Any] | None) -> dict[str, Any]:
    key = _market_key(payload)
    quote = (market or {}).get(key) if key else None
    market_summary = None
    if isinstance(quote, dict) and not quote.get("error"):
        market_summary = {
            "symbol": quote.get("symbol"),
            "price": quote.get("price"),
            "change_pct": quote.get("change_pct"),
            "volume": quote.get("volume"),
        }
    return {
        "date": payload.get("checked_at"),
        "test_id": payload.get("test_id"),
        "asset": payload.get("asset"),
        "verdict": payload.get("verdict"),
        "reason": list(payload.get("reason") or []),
        "risks": list(payload.get("risks") or []),
        "indicators": dict(payload.get("indicators") or {}),
        "missing": list(payload.get("missing") or []),
        "inputs_used": list(payload.get("inputs_used") or []),
        "market_summary": market_summary,
    }


def _market_key(payload: dict[str, Any]) -> str | None:
    test_id = payload.get("test_id")
    asset = payload.get("asset")
    if test_id == "ATTACK #001" or asset == "IREN":
        return "IREN"
    if test_id == "DEFENSE #001":
        return "GOLD"
    return None


def _reject_knowledge_path(path: Path) -> None:
    if any(part in path.parts for part in FORBIDDEN_PATH_PARTS):
        raise ValueError("log path must not target AI-Knowledge")
