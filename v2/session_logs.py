"""Reuse a complete local session log. No AI-Knowledge writes. No public identifiers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from v2.collect_report import quote_ok
from v2.logstore import _reject_canonical_write


def latest_log(
    log_dir: str | Path,
    *,
    log_kind: str,
    filename_prefix: str,
) -> tuple[dict[str, Any], Path] | None:
    """Newest readable collector log. Does not invent quotes."""
    root = Path(log_dir).expanduser().resolve()
    _reject_canonical_write(root)
    matches = sorted(
        root.glob(f"**/{filename_prefix}-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in matches:
        _reject_canonical_write(path)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(document, dict) and document.get("log_kind") == log_kind:
            return document, path
    return None


def find_complete_session_log(
    log_dir: str | Path,
    *,
    log_kind: str,
    filename_prefix: str,
    price_date: str,
) -> tuple[dict[str, Any], Path] | None:
    """Return the newest complete log for this market session, if any.

    Complete means quotes exist, holdings were readable, every quote is ok,
    and every quote shares the given price_date. Does not guess missing days.
    """
    root = Path(log_dir).expanduser().resolve()
    _reject_canonical_write(root)
    matches = sorted(
        root.glob(f"**/{filename_prefix}-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in matches:
        _reject_canonical_write(path)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not _is_complete_session(document, log_kind=log_kind, price_date=price_date):
            continue
        return document, path
    return None


def _is_complete_session(document: object, *, log_kind: str, price_date: str) -> bool:
    if not isinstance(document, dict):
        return False
    if document.get("log_kind") != log_kind:
        return False
    if document.get("holdings_error"):
        return False
    quotes = list(document.get("quotes") or [])
    if not quotes:
        return False
    for row in quotes:
        if not isinstance(row, dict) or not quote_ok(row):
            return False
        if row.get("price_date") != price_date:
            return False
    return True
